# Scheduler Architecture

## Goal

The scheduler must not scan every user on every tick. Running coaching jobs can
trigger Garmin sync, Google Calendar sync, database writes, and LLM calls, so the
worker must scale with the number of users that are actually due, not total user
count.

## Legacy Problem

The first temporary multi-user seam polled every minute and asked the
application layer for all runnable users. It then checked each user's
`timezone` and `schedule_times` in memory.

That remains available only as a compatibility fallback. It is not a product
scheduler:

- cost grows linearly with total users;
- most users are skipped on every tick;
- multiple workers can race without a lease;
- failures have no retry/backoff state;
- logs and metrics can grow from skipped users rather than actual jobs.

## Implemented Model

Use a due-job table with one row per scheduled user.

```text
user_preferences
  timezone
  schedule_times
  run_mode

scheduled_user_jobs
  athlete_id
  next_run_at
  lease_until
  locked_by
  last_run_at
  last_status
  failure_count
  next_retry_at
  last_error
```

The worker asks only for due jobs:

```sql
SELECT ...
FROM scheduled_user_jobs
WHERE disabled_at IS NULL
  AND next_run_at <= now()
  AND (next_retry_at IS NULL OR next_retry_at <= now())
  AND (lease_until IS NULL OR lease_until < now())
ORDER BY next_run_at ASC
LIMIT :batch_size
FOR UPDATE SKIP LOCKED;
```

This query uses an index on `next_run_at`, so the database finds due users
without scanning all users.

## Execution Flow

1. User is created or preferences change.
2. The application computes the next local scheduled time from `timezone` and
   `schedule_times`, converts it to UTC, and stores it as `next_run_at`.
3. Worker ticks at a small fixed interval.
4. Worker claims only due rows with a short lease.
5. Worker runs the coaching pipeline for each claimed user.
6. On success, it stores `last_run_at`, clears retry state, and computes the
   next `next_run_at`.
7. On failure, it increments `failure_count`, stores `last_error`, and sets
   `next_retry_at` with bounded exponential backoff.

## Why This Is Efficient

The worker tick still exists, but the tick does not inspect every user. The cost
is approximately:

```text
O(number of due jobs + index lookup)
```

not:

```text
O(total users)
```

For example, with 1,000,000 users and 80 due users, the worker claims roughly 80
rows instead of reading 1,000,000 profiles.

## Lease And Concurrency

The lease prevents duplicate execution:

- `locked_by` identifies the worker instance;
- `lease_until` expires stuck jobs;
- `FOR UPDATE SKIP LOCKED` lets multiple workers claim different rows.

Workers must use a bounded `batch_size` and a bounded concurrency limit. External
provider calls must never scale without a cap.

## Retry Policy

Failures should not create a hot loop.

Recommended initial policy:

- first failure: retry after 5 minutes;
- second failure: retry after 15 minutes;
- third failure: retry after 1 hour;
- later failures: retry after 6 hours;
- authentication failures should mark the provider `reauth_required` and stop
  scheduled attempts until the integration is fixed.

## Schedule Recalculation

`next_run_at` should be recalculated only when needed:

- user is created;
- user updates `timezone` or `schedule_times`;
- a scheduled run succeeds;
- an operator manually re-enables a disabled schedule.

The scheduler should not recompute every user's schedule every minute.

## Implementation Status

1. `scheduled_user_jobs` exists in the core schema.
2. `ScheduledUserJobService` computes `next_run_at`, claims due rows, and records
   success/failure state.
3. The local runtime user is upserted into the schedule table during runtime
   context resolution.
4. `MultiUserWorker.run_due()` uses due-job claim when the schedule service is
   wired.
5. `run_all()` remains only for explicit admin/manual operations.
6. The minute-match full-user scan remains only as a compatibility fallback for
   tests or deployments without the schedule service wired.
