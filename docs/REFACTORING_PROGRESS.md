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

### What this enables

- The same user-scoped coaching execution path can now be called from:
  - FastAPI user endpoints
  - the legacy CLI runtime
  - future worker entrypoints
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

- Per-user encrypted Garmin/Google credential migration into the database
- True multi-user background workers and per-user schedules/timezones
- Further SQL-level decomposition behind the history facades
- Full CLI migration away from direct deployment-config assumptions
- Docker end-to-end verification of the new user-facing runtime path

### Guardrails for the next slice

- Keep `TrainingOrchestrator` behavior-compatible while moving more workflow
  assembly into application services.
- Do not push new provider-specific logic into coaching modules.
- Prefer additive compatibility paths over renaming every `athlete_*` concept at
  once.
- Next persistence slice should extract `TrainingBackgroundService` or add the
  integration credential store; do not add more user API endpoints first.
