# Refactoring Progress

## 2026-04-24

This document tracks concrete refactoring slices that move the current codebase
toward the target architecture in
[`LONG_TERM_PRODUCTIZATION_PLAN.md`](./LONG_TERM_PRODUCTIZATION_PLAN.md) and
[`LONG_TERM_REFACTORING_STRATEGY.md`](./LONG_TERM_REFACTORING_STRATEGY.md).

### Completed in this slice

- Added a user-facing API surface with API-key authentication under `/v1`.
- Introduced `UserService` for product-facing identity, preferences, and API keys.
- Introduced `UserApplicationService` as the first user-scoped application layer.
- Added `CoachingApplicationService` so CLI and future API/worker paths can call
  the same coaching workflows.
- Added `UserCoachingStateService` to start decomposing write-side storage
  responsibilities out of `CoachingHistoryService`.
- Added `HistoryReadService`, `HistoryWriteService`, and `HistorySyncService`
  facades so orchestrator/runtime code no longer depends on the full
  `CoachingHistoryService` surface directly.
- Added `ServiceContainer.create_for_user(...)` and `UserContext`-aware
  orchestration.
- Added shared runtime composition via `create_application_runtime(...)` so CLI
  and FastAPI build the same application graph from one place.
- Made planner execution honor resolved user LLM settings and user-scoped
  `include_strength`.
- Reduced CLI responsibility:
  - the CLI now resolves a runtime user context through the application layer;
  - feedback, availability, goal, block, and injury commands go through
    application services;
  - the scheduler now accepts a callable job instead of depending directly on an
    orchestrator instance plus full settings.
- Split responsibility for user preference updates:
  - general user preferences stay in `UserService`;
  - LLM overrides are updated through `AdminSettingsService`.
- Added user-scoped write endpoints under `/v1/me/*` for:
  - feedback
  - availability
  - race goals
  - training blocks
  - injury status
- Moved CLI write commands onto the same user-scoped application methods used by
  the HTTP API.
- Rewrote the long-term refactoring strategy around current productization
  blockers instead of the original pre-refactor state.
- Started SQL-level history decomposition:
  - added shared athlete-scoped storage helpers;
  - extracted `PlanFreshnessService`;
  - moved active plan freshness, future plan reads, and stored Garmin workout id
    reads behind the new read-side service;
  - kept compatibility delegation on `CoachingHistoryService`.
- Added the first user-scoped integration credential/status store:
  - added `user_integration_credentials`;
  - added `IntegrationCredentialService`;
  - added an app-key-backed local credential cipher seam;
  - made user profile integration status prefer DB status before env
    compatibility fallback.
- Added a user runtime factory seam:
  - env-compatible Garmin users still use deployment credentials;
  - non-env users can resolve active Garmin credentials from the DB store;
  - coaching execution now asks the runtime factory for a container instead of
    directly constructing one.
- Added the first multi-user worker seam:
  - `UserService` can discover runnable users from DB state;
  - `UserApplicationService` exposes runnable `UserContext` values;
  - `MultiUserWorker` runs users one by one and isolates per-user failures;
  - service mode now schedules the multi-user worker while preserving the local
    env-compatible runtime user path.
- Replaced process-level scheduled run times with per-user schedule polling:
  - service mode polls every minute;
  - each user is due only when their own `timezone` and `schedule_times` match;
  - users outside their scheduled minute are reported as skipped instead of
    executed.

### What this enables

- The same user-scoped coaching execution path can now be called from:
  - FastAPI user endpoints
  - the legacy CLI runtime
  - the multi-user worker entrypoint
- The same user-scoped coaching input mutations can now be called from:
  - FastAPI user endpoints
  - the legacy CLI runtime
- The codebase now has an explicit seam between:
  - identity/preferences resolution
  - coaching execution
  - user-owned coaching state writes
  - history reads vs history writes vs sync-state mutations
  - transport surfaces such as CLI and HTTP

### Still not done

- Per-user Garmin token/session migration into the database
- Per-user Google credential migration into the database
- Per-user run mode preference instead of deployment-level service mode
- Further SQL-level decomposition behind the history facades
- Full CLI migration away from direct deployment-config assumptions
- Docker end-to-end verification of the new user-facing runtime path

### Guardrails for the next slice

- Keep `TrainingOrchestrator` behavior-compatible while moving more workflow
  assembly into application services.
- Do not push new provider-specific logic into coaching modules.
- Prefer additive compatibility paths over renaming every `athlete_*` concept at
  once.
- Next slice should move Google Calendar construction behind the user runtime
  factory or add a per-user run mode preference; do not add more user API
  endpoints first.
