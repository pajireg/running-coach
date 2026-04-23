# Long-Term Refactoring Strategy for Productization

This document is the implementation-facing refactoring strategy for executing
the direction in [LONG_TERM_PRODUCTIZATION_PLAN.md](LONG_TERM_PRODUCTIZATION_PLAN.md).

The goal is not to rewrite the coaching algorithm. The goal is to reshape the
current codebase so the same coaching semantics can support:

- multiple users;
- multiple client surfaces such as CLI, HTTP API, mobile apps, and workers;
- multiple integration providers such as Garmin, Apple ecosystem clients, and
  Android ecosystem clients.

This strategy is intentionally grounded in the current repository structure.
It identifies the existing structural bottlenecks, defines the target runtime
shape, and recommends a migration sequence that preserves behavior while
opening the path to long-term productization.

## Why This Document Exists

The product strategy is now broader than the current runtime shape.

Today, the codebase already contains the beginnings of a product surface:

- `src/running_coach/api/` exists;
- admin LLM settings already support global and per-user overrides;
- the coaching engine already has strong domain constraints and safety
  boundaries.

However, the main runtime path is still optimized for a single-user,
Garmin-centered deployment:

- `Settings` mixes deployment secrets, user-level behavior, and runtime flags;
- `ServiceContainer.create()` builds one singleton-like graph from one process
  configuration;
- `TrainingOrchestrator.run_once()` executes without a user-scoped input;
- `CoachingHistoryService` derives identity from `settings.garmin_email`;
- CLI assembly still acts as the primary application entrypoint.

Those choices were pragmatic for the current deployment, but they are the main
things that now block productization.

## Current Structural Gaps

### 1. Process Settings and User Settings Are Mixed

`src/running_coach/config/settings.py` currently holds:

- deployment secrets such as API keys;
- integration credentials such as Garmin email/password;
- runtime flags such as `service_mode`;
- user-affecting behavior such as `include_strength`, `schedule_times`, and
  planner defaults.

Why this blocks productization:

- one process configuration cannot represent multiple users safely;
- future mobile users cannot rely on env vars for preferences;
- runtime behavior cannot be cleanly derived per user.

### 2. The Container Is Built Around a Single Active User

`src/running_coach/core/container.py` builds one `ServiceContainer` from one
`Settings` object and wires:

- `GarminClient(email=settings.garmin_email, password=settings.garmin_password, ...)`
- `CoachingHistoryService(... athlete_key=settings.garmin_email.lower())`
- one `GeminiClient`
- one `GoogleCalendarClient`

Why this blocks productization:

- the container is keyed by a provider credential, not by an internal user;
- deployment wiring and user runtime wiring are fused together;
- there is no clean way to build a scoped container for `user_id=X`.

### 3. The Main Orchestrator Is Not User-Scoped

`src/running_coach/core/orchestrator.py` exposes:

- `TrainingOrchestrator.run_once(run_mode: str = "plan")`

The method reads everything indirectly from the already-wired container and
assumes one active Garmin login, one active history service, and one active
calendar client.

Why this blocks productization:

- workers cannot safely process different users in the same runtime model;
- API handlers cannot call the same orchestration path for arbitrary users;
- future mobile-triggered sync flows cannot reuse the orchestration path
  without process-global coupling.

### 4. Internal User Identity Is Coupled to Garmin Identity

`src/running_coach/storage/history_service.py` currently uses:

- `athlete_key=settings.garmin_email.lower()`
- `ensure_athlete(garmin_email=..., max_heart_rate=...)`
- `SELECT athlete_id FROM athletes WHERE external_key = %(external_key)s`

Why this blocks productization:

- Garmin email is acting as both an integration identifier and an internal user
  identity anchor;
- users without Garmin cannot fit the model cleanly;
- future provider-neutral identity becomes harder if every path begins from a
  Garmin credential.

### 5. Storage Responsibilities Are Too Broad

`CoachingHistoryService` currently handles:

- athlete creation/upsert;
- metrics and activity persistence;
- planned workout persistence;
- workout execution rebuilding;
- injury, feedback, availability, and goals;
- training background summarization;
- plan freshness logic;
- human-readable decision and calendar projection details.

Why this blocks productization:

- identity, preferences, credentials, and coaching history are not separated;
- test scope becomes too large for each change;
- user-scoped application services cannot depend on smaller persistence seams.

### 6. CLI and Scheduler Still Assemble the Business Workflow

`src/running_coach/__main__.py`:

- loads settings;
- builds the container;
- mutates runtime flags on `settings`;
- invokes feedback, availability, goal, injury, and run paths directly.

`src/running_coach/core/scheduler.py`:

- reads schedule times from process settings;
- binds one orchestrator instance to one schedule loop.

Why this blocks productization:

- CLI is not a thin entrypoint;
- the scheduler is process-scoped rather than user-scoped;
- API and worker flows cannot cleanly reuse the same application contracts.

### 7. Provider Clients Are Concrete Dependencies, Not Adapter Seams

The current `clients/` package is useful but still wired concretely:

- `GarminClient`
- `GoogleCalendarClient`
- `GeminiClient`

Why this blocks productization:

- new providers would force branching logic into runtime assembly and storage;
- provider capability boundaries are implicit rather than explicit;
- coaching modules risk accumulating provider-specific assumptions.

## Target Refactoring End State

The long-term target is a user-scoped, provider-neutral, application-service
architecture.

### Runtime Boundary

Every business workflow should begin from a user-scoped input such as:

- `user_id`
- `external_key`
- `UserContext`

The runtime must stop assuming that process configuration implies the active
user.

### Identity Boundary

Internal identity should be defined by the product model, not by Garmin.

Target direction:

- internal public term: `user`
- internal runtime key: `user_id`
- compatibility key: `external_key`
- integration identifiers remain provider-specific and separate

### Application Boundary

Business workflows should live in application services, not in CLI or raw API
handlers.

Examples:

- run one coaching cycle;
- create or extend a plan;
- sync completed activities;
- record feedback;
- update user preferences;
- register integration credentials.

### Coaching Boundary

`coaching/` remains the place for provider-neutral planning logic:

- context building;
- safety rules;
- legacy and LLM-driven planning;
- prompt rendering and validation.

Provider-specific payload handling should not leak into these modules.

### Integration Boundary

Provider clients should be refactored into explicit adapter seams for:

- activity and recovery ingestion;
- workout delivery;
- calendar projection;
- LLM planning provider calls.

This is the boundary that must absorb Garmin, future Apple ecosystem clients,
future Android ecosystem clients, and additional LLM providers.

### Persistence Boundary

Persistence should be split into narrower responsibilities:

- user identity;
- user preferences and effective settings;
- integration credentials and status;
- activities and health metrics;
- planned workouts and workout execution;
- feedback, injuries, availability, and goals;
- coach decisions and planning snapshots.

### Surface Boundary

CLI, HTTP API, scheduled workers, and future mobile-triggered actions should
all invoke the same application services.

## Refactoring Principles

- Preserve coaching behavior before expanding runtime surfaces.
- Separate deployment defaults from user preferences.
- Separate provider credentials from provider clients.
- Do not let provider identifiers define internal user identity.
- Keep CLI thin and move business actions into callable services.
- Keep API handlers thin and user-scoped.
- Normalize provider payloads before coaching logic reads them.
- Keep provider SDK concerns out of coaching modules.
- Favor additive migration and compatibility layers over big-bang rewrites.
- Allow old and new paths to coexist until behavior parity is proven.

## Recommended Codebase Shape

The codebase does not need a total rename immediately, but responsibilities
should move toward the following shape.

### `config/`

Should contain deployment configuration and process defaults only:

- database URL;
- deployment API keys;
- encryption key references;
- default planner fallback;
- default locale fallback.

It should not remain the primary home for user-level preferences.

### `application/`

Introduce a dedicated application layer for user-scoped use cases.

Suggested responsibilities:

- orchestration use cases;
- feedback and preference update flows;
- integration registration flows;
- sync flows;
- user context resolution;
- effective settings resolution.

### `coaching/`

Keep the current package and preserve its role as the provider-neutral planning
layer.

### `integrations/` or evolved `clients/`

Refactor external providers into adapter-oriented modules instead of treating
them as one-off concrete dependencies.

### `storage/`

Move toward repository- or service-level separation by bounded responsibility.

### `core/`

Reduce `core/` to runtime composition concerns:

- dependency assembly;
- scheduler loop;
- worker startup;
- shared process-level runtime bootstrapping.

## Refactoring Workstreams

### Workstream A: Identity and User Context

Introduce a first-class `UserContext` runtime model.

It should eventually contain:

- stable internal user identity;
- external key;
- resolved user preferences;
- integration status summary;
- effective planner settings.

Primary refactors:

- stop deriving active runtime identity from `settings.garmin_email`;
- make orchestrator-facing workflows accept `user_id` or `UserContext`;
- keep `athlete` naming only as an internal storage compatibility concern.

Target public shapes:

- `run_once(user_id=...)`
- `create_for_user(settings, user_id)`
- `resolve_user_context(user_id)`

### Workstream B: Settings and Effective Preference Resolution

Split process configuration from per-user behavior.

Primary refactors:

- shrink `Settings` to deployment defaults and secrets;
- introduce DB-backed user preference resolution;
- allow admin/system defaults plus per-user overrides;
- stop mutating `Settings` at runtime in CLI entrypoints.

Target resolution order:

1. user override
2. admin/system default
3. deployment fallback

This rule should apply consistently to planner mode, model/provider, locale,
schedule configuration, include-strength behavior, and future notification or
mobile preferences.

### Workstream C: Application Service Extraction

Break the current `TrainingOrchestrator` workflow into callable user-scoped
services.

Suggested service boundaries:

- `RunCoachingCycle`
- `DeterminePlanMode`
- `CreatePlan`
- `ExtendPlan`
- `SyncCompletedActivities`
- `RecordFeedback`
- `UpdateAvailability`
- `UpdateGoals`
- `UpdateInjuryStatus`

The goal is not to delete `TrainingOrchestrator` immediately. The goal is to
turn it into a thin coordinator over explicit use cases instead of the sole
owner of the entire business flow.

### Workstream D: Persistence Decomposition

Split `CoachingHistoryService` into narrower seams.

Recommended responsibility slices:

- identity repository
- user preference repository
- integration credential repository
- activity and health history repository
- planned workout repository
- workout execution repository
- coaching input repository for feedback, injuries, availability, goals
- decision log and plan snapshot repository

Also separate:

- CRUD-style persistence
- derived state summarization
- presentation/projection helpers

This reduces the blast radius of future user-scoped and provider-neutral
changes.

### Workstream E: Integration Adapter Refactor

Refactor concrete provider clients behind explicit capability boundaries.

Recommended capability groups:

- health/activity ingestion
- recovery/performance ingestion
- workout delivery
- calendar projection
- LLM planning provider

This allows:

- Garmin to remain supported;
- Apple ecosystem integrations to plug in later;
- Android ecosystem integrations to plug in later;
- multiple LLM providers to remain a client-layer concern.

### Workstream F: Composition and Runtime Assembly

Replace one global container assembly path with layered composition.

Recommended target:

- one deployment-level bootstrap;
- one user-scoped container builder;
- one application-service graph per active user.

Primary refactors:

- split `ServiceContainer.create()` into deployment/runtime-safe construction
  steps;
- introduce `create_for_user(...)` or an equivalent user-scoped builder;
- ensure workers resolve a user first, then build the graph for that user.

### Workstream G: CLI, API, and Scheduler Surface Refactor

Make every surface thin and service-driven.

CLI target:

- parse arguments;
- resolve user target;
- call application service;
- render logs or operator output.

API target:

- authenticate;
- resolve current user;
- call application service;
- serialize response.

Scheduler target:

- register schedules per resolved user settings;
- invoke the same user-scoped run service used by CLI and API flows.

### Workstream H: Migration Safety and Observability

Refactor with compatibility, not interruption.

Required guardrails:

- keep bounded metric labels;
- keep structured logs user-aware without adding unbounded metric dimensions;
- keep old paths operational while new paths gain parity;
- avoid destructive renames until compatibility is proven;
- track integration status independently per provider.

## Recommended Refactoring Sequence

### Phase 1: Introduce User-Scoped Identity Without Changing Planning

- Add `UserContext` and user-resolution seams.
- Keep planner behavior unchanged.
- Keep current storage tables working.

Do not mix with:

- planner algorithm redesign;
- mobile client implementation;
- full table rename.

### Phase 2: Split Deployment Settings from Effective User Settings

- Move user behavior resolution away from env-only settings.
- Keep deployment secrets in `Settings`.
- Make effective settings resolvable per user.

Do not mix with:

- provider adapter redesign;
- broad API feature expansion.

### Phase 3: Extract Application Services from CLI and Orchestrator

- Introduce service-level entrypoints for coaching cycle and user updates.
- Reduce CLI to argument parsing and output.
- Keep `TrainingOrchestrator` as a compatibility coordinator during migration.

Do not mix with:

- storage rename;
- watch/mobile implementation.

### Phase 4: Decompose Persistence Responsibilities

- Split `CoachingHistoryService` by bounded domain concerns.
- Keep existing queries and semantics stable where possible.
- Introduce user-scoped repositories.

Do not mix with:

- Garmin sync behavior rewrite;
- coaching rule changes.

### Phase 5: Refactor Provider Clients Behind Capability Interfaces

- Make Garmin, Calendar, and LLM integrations adapter-oriented.
- Keep current Garmin behavior intact behind the new seam.

Do not mix with:

- full second-provider implementation;
- premature abstraction beyond current needs.

### Phase 6: Rebuild Container and Worker Runtime Around User Scope

- Build user-scoped service graphs.
- Load user preferences before registering schedules.
- Support one worker per user cleanly.

Do not mix with:

- large UI or mobile product work;
- remaining naming cleanup.

### Phase 7: Expand the HTTP API on Top of the New Service Layer

- Add user-facing endpoints on the new application services.
- Keep admin surface separate.
- Reuse current-user resolution everywhere.

Do not mix with:

- deep schema rename;
- planner semantics changes.

### Phase 8: Add Mobile and Wearable Provider Paths

- Add Apple and Android ecosystem integrations only after the provider-neutral
  service path is stable.
- Keep new integrations within adapter boundaries.

Do not mix with:

- rewiring coaching logic around provider-specific fields;
- watch app implementation details inside core runtime modules.

### Phase 9: Clean Up Remaining Legacy Naming and Compatibility Shims

- Rename internal `athlete` references only after runtime and API stability.
- Prefer compatibility views or aliases when migration risk is high.

## Important Public Interface and Type Changes

The long-term direction should result in the following public runtime shapes.

### Runtime and Service Contracts

- `run_once(user_id=...)`
- `create_for_user(settings, user_id)`
- `resolve_effective_user_settings(user_id)`
- `resolve_user_context(user_id)`

### Integration Contracts

- `register_integration_credential(user_id, provider, payload)`
- `get_integration_status(user_id, provider)`
- `sync_plan_delivery(user_id, target_provider)`

### API Contracts

- user-facing APIs use `user`, not `athlete`;
- current user is resolved from auth, not from caller-provided implicit global
  state;
- admin paths stay privileged and separate from user paths.

## Verification Strategy

### Unit Tests

- effective user settings resolve correctly from user override, then admin
  default, then deployment fallback;
- user context resolution is correct and isolated;
- adapter normalization produces provider-neutral activity and recovery inputs;
- provider status and credentials are stored independently per user.

### Service Tests

- two users can run the same orchestration path without state crossover;
- `skip`, `extend`, and `replan` semantics remain unchanged;
- rest-day skip logic remains based on `session_type == "rest"`;
- Garmin cleanup still uses stored workout IDs rather than titles.

### API Tests

- authenticated user requests resolve the correct current user;
- one user's auth cannot access another user's state;
- API handlers and CLI commands invoke the same underlying application services.

### Integration Tests

- Docker startup can run a user-scoped worker cleanly;
- Postgres-backed user preference and credential state load before scheduled
  execution;
- provider-specific sync state does not leak between providers or between users.

### Regression Focus

- preserve the current coaching algorithm behavior;
- preserve current planner safety rules;
- preserve current Garmin and Google Calendar sync invariants while internal
  seams move.

## Non-Goals and Risks

### Non-Goals

- immediate rewrite of coaching rules or plan semantics;
- immediate full rename of every `athlete_*` symbol;
- immediate implementation of HealthKit, Health Connect, or watch apps;
- replacing Garmin before equivalent provider-neutral seams exist;
- introducing abstraction layers that are broader than the real next step.

### Main Risks

- decomposing `CoachingHistoryService` may unintentionally change behavior;
- mixed `athlete` and `user` terminology may confuse implementation if not
  clearly bounded;
- provider abstraction may become over-engineered before a second full provider
  path exists;
- moving logic out of CLI and orchestrator may fragment behavior if service
  boundaries are not chosen carefully.

### Risk Response

- start from seams around current code, not from abstract frameworks;
- keep migrations additive where possible;
- preserve existing behavior with regression tests before deleting legacy paths;
- introduce compatibility layers first, rename later.

## Implementation Defaults

Use these defaults unless a later implementation plan explicitly overrides them:

- public product/API term: `user`
- internal storage compatibility term: `athlete` may remain temporarily
- orchestration entrypoint shape: user-scoped
- coaching engine: provider-neutral
- deployment config source: `Settings`
- user behavior source: DB-backed effective settings
- external providers: adapter-oriented boundaries
- migration style: additive, compatibility-first
