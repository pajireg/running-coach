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

Remaining productization blockers:

- `CoachingHistoryService` still owns too much SQL and derived state logic;
- Garmin and Google credentials are still deployment/env compatible, not
  user-owned encrypted records;
- provider clients are still concrete runtime dependencies;
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

Required behavior:

- discover active users from DB;
- use each user's timezone, schedule times, and run mode;
- isolate failures per user;
- call the same application service used by CLI/API;
- keep metric labels bounded and avoid `user_id` metric labels.

## Execution Sequence

1. Extract `PlanFreshnessService` and wire read-side callers to it.
2. Extract `TrainingBackgroundService` and migrate context-builder reads.
3. Add `user_integration_credentials` schema and service with encryption
   interface.
4. Update user profile/API integration status to read DB integration status
   before env compatibility fallback.
5. Introduce a user runtime factory and move Garmin/Google construction behind
   credential-aware seams.
6. Convert scheduler execution to user discovery plus per-user jobs.
7. Add provider capability protocols and migrate Garmin behind them.
8. Add Apple/Android adapter skeletons only after the above runtime path is
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
