# Long-Term Refactoring Strategy for Productization

This document is the implementation plan for evolving Running Coach from a
single-user Garmin-centered runtime into a multi-user, API-first coaching
backend that can support Garmin, Apple Watch + iPhone, and Wear OS + Android
over time.

The goal is not to rewrite coaching quality rules. The goal is to remove the
runtime, persistence, and integration coupling that prevents the existing
coaching semantics from serving multiple users and multiple client surfaces.

## Current State

Completed structural work:

- user-facing `/v1` API with API-key authentication;
- `UserContext` and DB-backed user preferences;
- `UserApplicationService` and `CoachingApplicationService`;
- shared CLI/FastAPI runtime composition;
- user-scoped orchestration entrypoints;
- initial read/write/sync history facades;
- user coaching state writes separated from the monolithic history service.
- initial user integration credential/status table and storage service.
- user runtime factory seam for resolving env-compatible or DB-backed Garmin
  credentials before container creation.
- initial provider capability protocols for training data and workout delivery,
  with Garmin Connect still used as the default concrete provider.
- orchestrator now reads health/activity/history data and workout delivery
  through provider-neutral container accessors, while keeping Garmin Connect as
  the default provider and preserving existing Garmin sync fields.
- provider data storage is moving to canonical-first naming:
  `provider` + provider-native external ids for activities, and
  provider-neutral workout delivery fields for planned workouts.
- raw provider payloads are treated as diagnostics/compatibility data, not the
  long-term product model; see [`PROVIDER_DATA_MODEL.md`](./PROVIDER_DATA_MODEL.md).

Remaining productization blockers:

- `CoachingHistoryService` still owns too much SQL and derived state logic;
- Google Calendar runtime is still deployment/local-file compatible;
- Garmin DB credential storage is wired into runtime creation, but real token
  migration and reauth flows are not implemented yet;
- provider clients are partially abstracted, but runtime construction still
  resolves Garmin as the only real training data provider;
- some compatibility migration paths still reference legacy Garmin DB columns;
- scheduler/runtime execution is still effectively single-user;
- mobile/watch provider strategy exists in product docs, but backend adapter
  seams are not ready.

## Refactoring Priorities

### 1. Decompose Persistence Before Expanding Features

The next work must reduce `CoachingHistoryService` at the SQL level, not add
more facades around it.

Target services:

- `PlanFreshnessService`: active plan, `skip`/`extend`/`replan` freshness, and
  future plan reads;
- `TrainingBackgroundService`: long-term volume, adherence, recovery, and
  planning context summaries;
- `ActivityHistoryService`: activity and health metric persistence/reads;
- `PlannedWorkoutStore`: planned workout persistence and Garmin sync ids;
- `WorkoutExecutionStore`: execution matching and backfill state;
- `CoachingInputStore`: feedback, availability, goals, blocks, and injuries.

Rules:

- preserve existing `skip`, `extend`, and `replan` semantics;
- keep compatibility methods on `CoachingHistoryService` until callers are
  migrated;
- move one bounded SQL responsibility at a time and keep regression tests close
  to each moved service.

### 2. Move Integration State Into User-Scoped Storage

The next product blocker after persistence decomposition is credential ownership.

Add a user-scoped integration credential model:

- provider values: `garmin`, `google_calendar`, later `healthkit`,
  `health_connect`, and `google_fit`;
- encrypted JSON payload;
- status: `active`, `reauth_required`, `disabled`, `error`;
- `last_validated_at`, `last_error`, and timestamps;
- `ON DELETE CASCADE` from `athletes`.

Initial implementation should keep existing env/local-token compatibility as
`env_compat`, while exposing the DB-backed service and status flow. Do not try
to migrate Garmin sessions and Google OAuth tokens in the same slice that adds
the schema.

### 3. Introduce Provider Capability Adapters

Provider-specific SDK behavior must stay out of coaching and orchestration.

Capability boundaries:

- health/activity ingestion;
- workout delivery;
- calendar projection;
- LLM planning provider calls.

Garmin should be the first adapter behind these boundaries. Apple HealthKit,
watchOS, Health Connect, Google Fit, and Wear OS should only be implemented
after credential storage and worker execution no longer assume one env user.

### 4. Make Runtime Assembly User-Scoped

`ServiceContainer.create_for_user(...)` exists, but it still creates provider
clients from deployment credentials.

Target shape:

- process-level `ApplicationRuntime` owns deployment defaults and shared DB
  services;
- user execution resolves `UserContext` and integration credentials first;
- a user runtime factory creates provider adapters from user-owned credentials;
- missing credentials produce explicit `reauth_required` or `not_configured`
  outcomes instead of falling through to env credentials for non-local users.

### 5. Convert Scheduler Into Multi-User Worker

After credential/runtime seams are stable, replace the singleton scheduler
model with a user worker model.

Current state:

- service mode schedules a `MultiUserWorker` entrypoint;
- runnable users are discovered from DB state;
- the legacy deployment user remains runnable via env-compatible Garmin
  credentials;
- additional users require an active Garmin credential row before the worker
  picks them up;
- failures are isolated per user and returned in an aggregate worker summary.
- service mode polls every minute and each user is due only when their own
  timezone-adjusted local time matches `schedule_times`.
- scheduled execution uses each user's `run_mode` preference before falling
  back to the deployment default.
- due execution uses `scheduled_user_jobs.next_run_at` claim/lease state instead
  of scanning every runnable user on each normal service tick.
- Google Calendar client construction is resolved by the user runtime factory:
  env-compatible users can use the local token file, while non-env users need an
  active DB credential row or calendar sync is disabled.

Required behavior:

- call the same application service used by CLI/API;
- keep metric labels bounded and avoid `user_id` metric labels.

## Execution Sequence

1. Extract `PlanFreshnessService` and wire read-side callers to it.
2. Extract `TrainingBackgroundService` and migrate context-builder reads.
3. Migrate Garmin and Google credential flows into `user_integration_credentials`.
4. Add provider capability protocols and migrate orchestrator calls behind them.
5. Persist refreshed per-user Google OAuth tokens back into the credential store.
6. Add Apple/Android adapter skeletons only after the above runtime path is
   user-scoped end to end.

## Verification Requirements

Every persistence, scheduling, Garmin upload, or Google Calendar sync change
requires:

- focused unit tests for the touched service;
- orchestrator regression tests for `skip`, `extend`, and `replan` if plan
  freshness or execution matching is touched;
- Docker stack verification before completion is reported.

Use additive compatibility and small commits. Do not rename `athletes` or
`athlete_id` broadly until API, worker, credential, and export/deletion paths
are stable.
