# Long-Term Productization Plan

This document is the implementation-facing plan for evolving Running Coach from a
single-user CLI/service into a multi-user, mobile-friendly coaching backend and,
over time, a multi-client coaching platform that supports Garmin Connect,
Apple Watch + iPhone, and Wear OS + Android.

Use **user** as the product and API term. The current code and schema still use
`athlete` in several places; treat those names as legacy/internal compatibility
terms until they are migrated. New public APIs, docs, and product-facing models
should use `user`.

## Target Outcome

Running Coach should become an API-first backend that can serve multiple users,
each with independent coaching history, preferences, integrations, and scheduled
execution.

Long term, the product should support multiple execution and data-ingestion
surfaces:

- Garmin Connect as an external training and workout-delivery provider;
- Apple Watch + iPhone as a first-class mobile and wearable ecosystem;
- Wear OS + Android as a first-class mobile and wearable ecosystem.

The mobile app should eventually become the primary user-facing product surface
for authentication, settings, feedback, notifications, workout review, and
integration management. Watches should start as companion experiences tied to
the phone app rather than independent product surfaces.

The first production-oriented milestone is a **multi-user MVP**:

- Mobile clients authenticate with a per-user API key.
- User preferences are stored in Postgres, not in process-wide environment
  variables.
- Garmin and Google integration tokens are encrypted in Postgres.
- The service can run one user's scheduled coaching worker per container.
- The existing CLI remains available as an operator/developer tool.
- Coaching behavior, safety rules, and planner semantics remain unchanged unless
  a later coaching-quality initiative explicitly changes them.

## Terminology

### Preferred Terms

- `user`: public product/API term for the person using Running Coach.
- `user_id`: preferred long-term primary identifier in new product-facing code.
- `external_key`: stable external identifier for imports, admin scripts, or
  compatibility flows.
- `user_preferences`: per-user configuration.
- `user_integration_credentials`: encrypted integration state for Garmin,
  Google, and future providers.

### Legacy Terms

- `athlete`: current schema/code term.
- `athlete_id`: current canonical DB primary key.
- `athletes`: current identity table.

Do not block the MVP on a full rename from `athlete` to `user`. The safe path is:

1. Add new public/API code using `user`.
2. Keep existing DB tables working.
3. Introduce compatibility views or aliases where useful.
4. Rename storage internals only after API, tests, and migration strategy are
   stable.

## Architecture Direction

### Identity and Access

Use API-key authentication for the MVP.

- Add a table for user API keys.
- Store only a hash of each API key.
- Return the raw API key only once at creation time.
- Require `Authorization: Bearer <api_key>` on user-scoped endpoints.
- Resolve the API key to exactly one current user before any business logic runs.
- Never allow clients to pass arbitrary `user_id` values to access another
  user's data.

The API-key model is intentionally simple. It can later be replaced or wrapped
by mobile login, OAuth, or JWT sessions without changing the core coaching
orchestrator.

### Per-User Configuration

Process-wide `Settings` should remain for deployment defaults and service
secrets only.

Move user-specific behavior into Postgres:

- timezone
- schedule times
- service run mode
- include strength
- planner mode
- preferred LLM model/provider
- max heart rate
- preferred language/locale for user-facing coaching copy
- calendar sync preferences
- notification preferences when introduced

Use DB preferences first, falling back to `Settings` defaults only when the user
has not configured a value.

User-facing coaching copy should resolve from the user's preferred locale.
Korean remains the compatibility default for the current single-user deployment,
but new user-facing APIs, workout descriptions, calendar text, notifications,
and LLM rationale fields should be designed so the output language can vary per
user. Keep internal code, technical docs, canonical workout names, and safety
rule identifiers language-neutral or English where possible; localize only the
presentation text that users read.

Do not add new `COACH_*` environment variables for behavior that should become
user-specific.

### Integration Credentials

Store per-user integration state encrypted at rest.

Required MVP providers:

- `garmin_session`
- `google_calendar_token`

Recommended shape:

- `provider`: bounded enum-like text value
- `encrypted_payload`: encrypted JSON bytes/text
- `status`: `active`, `reauth_required`, `disabled`, `error`
- `last_validated_at`
- `last_error`
- timestamps

Use app-level symmetric encryption for the MVP via a deployment secret such as
`APP_ENCRYPTION_KEY`. External KMS can be added later behind the same encryption
service interface.

Garmin password handling:

- Do not store Garmin passwords long term.
- Use email/password/MFA only for the initial session creation or explicit
  reauthentication.
- Persist the resulting session token payload encrypted in Postgres.
- If Garmin requires MFA or the token expires, mark the integration as
  `reauth_required`.

Google Calendar handling:

- Keep OAuth client configuration as deployment-level configuration.
- Store each user's authorized token JSON encrypted in Postgres.
- Refresh tokens server-side when possible.
- Mark the integration `reauth_required` when refresh fails.

### Mobile and Wearable Product Strategy

Running Coach should evolve from a Garmin-centric operator tool into a
multi-client coaching product that supports:

- `Garmin Connect`
- `Apple Watch + iPhone`
- `Wear OS + Android`

Product direction:

- Keep the coaching engine, safety rules, and planning pipeline device-agnostic.
- Treat mobile apps as the primary user-facing product surface over time.
- Treat watch experiences as companion surfaces for workout execution, glanceable
  status, and notifications, not as the initial system of record for identity,
  billing, or configuration.
- Keep Garmin as a supported first-class provider rather than a legacy-only
  bridge.
- Expand to Apple and Android ecosystems as additional product channels, not as
  a rewrite of the coaching core.

Platform-specific SDK and device logic should stay inside client and integration
boundaries. Coaching, storage, and orchestration layers should continue to work
with provider-neutral concepts such as user, activity, recovery state, planned
workout, and workout-delivery target.

### Health Data and Workout Delivery Strategy

Long-term health and workout integrations should follow a provider-neutral model
with ecosystem-specific adapters.

Apple ecosystem:

- Use `HealthKit` as the primary health and workout data ingress point on
  iPhone.
- Support `Apple Watch` workout execution and status delivery through a watchOS
  companion app tied to the iPhone app.
- Allow Apple ecosystem users to receive coaching value even when they do not
  connect Garmin.

Android ecosystem:

- Use `Health Connect` as the primary Android health-data platform.
- Treat `Google Fit` as a compatibility or migration path, not as the default
  long-term Android integration target.
- Support `Wear OS` workout execution and status delivery through a companion
  experience tied to the Android app.

Cross-platform principles:

- Normalize provider-specific raw fields into provider-neutral internal models
  before coaching logic reads them.
- Keep the internal source of truth in Postgres and user-scoped orchestration,
  not in any device ecosystem.
- Allow one user to connect multiple providers over time.
- Define source-priority and merge rules explicitly when multi-provider conflict
  handling is implemented, rather than hard-coding implicit precedence into the
  coaching layer.
- Continue treating Google Calendar as a presentation and review layer, not as
  a health-data or execution source of truth.

### LLM Provider and Cost

Use a service-owned default LLM API key for the MVP.

User preferences may choose planner mode/model if supported, but user-specific
LLM API keys are out of scope for the first milestone.

LLM model configuration should resolve in this order:

1. user override from preferences;
2. global default from admin/system settings stored in Postgres;
3. deployment fallback from process settings.

The global default should include `planner_mode`, `llm_provider`, and
`llm_model`. A user's preference row may override any supported subset of those
fields. Empty user override fields mean "inherit the global default."

New LLM features should move toward an `LLMProvider` protocol. Do not introduce
new direct `google.genai` calls outside the existing Gemini client/planner files.
Provider-specific wire details must stay in the client layer, not in coaching
modules.

Long term, remove hard-coded model constants such as `GEMINI_MODEL` from
coaching-time decision paths. The selected provider/model should be passed as
runtime configuration when the LLM call is made. Gemini-specific model names and
request details should be interpreted only by the Gemini client layer; coaching
planners should not hard-code provider-specific identifiers.

Changing the configured model does not rewrite already generated plans. The new
effective model applies from the next `replan`, one-day `extend`, or manual sync
that invokes the planner.

### Admin Console

Add a separate administrator surface for operational configuration. This is not
part of the user-facing mobile API.

MVP scope:

- one `/admin` API namespace;
- one admin web page for LLM settings;
- global default LLM provider/model/planner mode management;
- per-user LLM override lookup and edit;
- effective model visibility for each user.

Out of scope for the first admin-console milestone:

- user creation;
- user API-key management;
- Garmin or Google reauthentication;
- manual coaching run triggers;
- broad system observability dashboards.

Admin authentication should start with a deployment-provided admin API key.

- Inject the raw `ADMIN_API_KEY` via environment/secret manager.
- Do not store the raw admin API key in Postgres.
- For the MVP, comparing against the deployment secret is acceptable.
- A later version can store hashed admin keys with names, scopes, and rotation
  metadata.
- User API keys must never authorize `/admin/*` requests.

Admin settings storage should use a system/admin settings table for global
defaults, separate from per-user preferences. The table should store bounded
keys or typed columns for:

- default planner mode;
- default LLM provider;
- default LLM model.

Initial admin API endpoints:

- `GET /admin/llm-settings`
  - return global default provider, model, and planner mode.
- `PATCH /admin/llm-settings`
  - update global default provider, model, and planner mode.
- `GET /admin/users/{user_id}/llm-settings`
  - return the user's overrides plus effective provider, model, and planner
    mode after fallback resolution.
- `PATCH /admin/users/{user_id}/llm-settings`
  - set, update, or clear the user's LLM overrides.

The first admin UI should be a single LLM Settings page:

- global default provider/model/planner mode selectors;
- user override table;
- effective provider/model/planner mode display;
- save behavior that affects future plan generation only.

Keep `/admin` handlers separated from `/v1` user API handlers. Admin handlers may
accept explicit `user_id` path parameters because they are privileged operator
tools; user API handlers should continue deriving the current user from the
authenticated user API key.

### Execution Model

Support one scheduled user worker per container for the MVP.

The container should accept a target user identifier, for example:

- `RUNNING_COACH_USER_ID`
- or a CLI flag such as `running-coach run --user-id ... --service`

At startup, the worker should:

1. Load deployment `Settings`.
2. Load the user record, preferences, and encrypted integration credentials.
3. Build a user-scoped service container.
4. Register that user's configured schedule times.
5. Run `auto` mode by default unless the user's preference says otherwise.

Important implementation constraint:

- The orchestration function must be user-scoped, for example
  `run_once(user_id=...)`.
- Do not hide user selection inside global settings.
- This keeps the door open for a future DB-polling worker that processes many
  due users in one process.

## Implementation Phases

### Phase 1: User-Scoped Core Without Public API

Goal: make the existing pipeline callable for a specific user while preserving
current CLI behavior.

Key changes:

- Introduce a `UserContext` model containing identity, preferences, and
  integration status.
- Add a storage service that can load users and preferences by ID/API key.
- Add user preference tables while keeping current `athletes` data usable.
- Add encrypted credential storage and an encryption service.
- Add `ServiceContainer.create_for_user(settings, user_id)`.
- Extend `TrainingOrchestrator.run_once()` to accept a user context or user ID.
- Keep current `.env` single-user behavior as a compatibility path.

Acceptance criteria:

- Existing tests still pass.
- A test can create two users and run storage/orchestration paths without data
  crossing between users.
- No new user-specific setting is read only from environment variables.

### Phase 2: Mobile-Ready HTTP API

Goal: expose the minimum API surface a mobile app needs.

Add FastAPI and create `src/running_coach/api/`.

MVP endpoints:

- `POST /v1/users`
  - create a user and return a one-time API key.
- `GET /v1/me`
  - return current user profile, preferences, and integration status.
- `PATCH /v1/me/preferences`
  - update timezone, locale/preferred language, schedule times, planner mode,
    scheduled run mode, include strength, and similar user-scoped settings.
- `POST /v1/integrations/garmin/session`
  - perform initial Garmin authentication and store encrypted session state.
- `POST /v1/integrations/google/token`
  - store or refresh Google token state.
- `POST /v1/runs/sync`
  - trigger the current user's coaching pipeline in `auto` mode.
- `GET /v1/plans/current`
  - return current and future planned workouts.
- `POST /v1/feedback`
- `POST /v1/availability`
- `POST /v1/goals`
- `POST /v1/injuries`

The Phase 2 API should also leave room for future native mobile ecosystems
without forcing a redesign of user identity or integration storage. Long-term
capability areas include:

- mobile session and device registration;
- per-ecosystem integration status;
- workout delivery target selection;
- push-notification preferences;
- background sync capability reporting.

The same user integration credential model should be able to accommodate future
providers such as:

- `apple_healthkit`
- `android_health_connect`
- `google_fit_legacy`

Admin endpoints are intentionally separate from `/v1` user endpoints:

- `GET /admin/llm-settings`
- `PATCH /admin/llm-settings`
- `GET /admin/users/{user_id}/llm-settings`
- `PATCH /admin/users/{user_id}/llm-settings`

API rules:

- All `/v1/me`, integration, plan, and coaching input endpoints require API-key
  auth.
- All `/admin/*` endpoints require admin API-key auth.
- Auth middleware/dependencies resolve the user once and pass a user context
  into handlers.
- User API keys must fail against `/admin/*`.
- Handlers should call service/orchestrator functions, not duplicate business
  logic.
- API responses should use `user` terminology even if storage still maps to
  `athlete_id` internally.

Acceptance criteria:

- API tests cover authentication success/failure.
- A user cannot read or mutate another user's data.
- Feedback, availability, goals, and injuries written through the API appear in
  the existing coaching context.

### Phase 3: User Worker Containers

Goal: run scheduled coaching independently per user.

Key changes:

- Add CLI support for `--user-id` and `--external-key`.
- Add container environment support for `RUNNING_COACH_USER_ID`.
- At service startup, load user preferences from DB before registering schedule
  jobs.
- Ensure logs include a bounded user reference such as user ID in structured log
  fields where appropriate, but do not add user IDs as Prometheus counter labels.
- Keep Docker examples for both legacy single-user and user-scoped service mode.

Acceptance criteria:

- Two worker containers can run against the same Postgres database for different
  users without sharing Garmin, Google, or coaching state.
- Rest days still skip Garmin upload and Google Calendar plan sync.
- Auto mode still returns `skip`, `extend`, or `replan` according to existing
  freshness semantics.

### Phase 4: Storage Rename and Compatibility Cleanup

Goal: migrate internal naming from `athlete` to `user` only after the API shape
is stable.

Safe migration path:

- Add `users` as the preferred identity table or create a compatibility view over
  `athletes`.
- Decide whether to rename `athlete_id` columns or keep them internally.
- If renaming, migrate with explicit compatibility views and data export/delete
  tests.
- Update docs and code references in a controlled branch.

Do not mix this broad rename with behavior changes in Garmin sync, scheduler
logic, or coaching rules.

### Phase 5: Mobile App Foundation

Goal: make iOS and Android apps first-class product surfaces without changing
coaching semantics.

Key changes:

- Add mobile-oriented auth/session flows on top of the user identity model.
- Add device registration, notification preference, and sync-status primitives.
- Expose plan review, feedback input, settings, and integration status in
  mobile-ready APIs.
- Keep the mobile app as a thin product layer over existing orchestrator and
  storage services.

Acceptance criteria:

- A user can authenticate from a mobile client and read current plan data.
- Mobile clients can update settings, submit feedback, and inspect integration
  status without direct access to internal storage concepts.
- Device registration and notification preferences are user-scoped and
  independently stored.

### Phase 6: Apple Ecosystem Integration

Goal: support an Apple-native coaching experience through iPhone and Apple
Watch.

Key changes:

- Add `HealthKit` ingestion through the iPhone app.
- Add a watchOS companion app for workout delivery, status display, and
  completion signaling.
- Add Apple ecosystem integration state to the user credential and integration
  model.

Acceptance criteria:

- A user can connect the Apple ecosystem without connecting Garmin.
- HealthKit-backed runs and relevant recovery signals can enter the coaching
  pipeline through normalized provider-neutral models.
- Planned workouts can be delivered to the Apple Watch companion path with
  trackable sync status.

### Phase 7: Android Ecosystem Integration

Goal: support an Android-native coaching experience through Android phones and
Wear OS devices.

Key changes:

- Add `Health Connect` ingestion as the default Android health-data path.
- Add a Wear OS companion experience for workout delivery, status display, and
  completion signaling.
- Support `Google Fit` only as a compatibility or migration layer where needed.

Acceptance criteria:

- A user can connect Android-native health data without Garmin.
- Health Connect-backed runs and relevant recovery signals can enter the
  coaching pipeline through normalized provider-neutral models.
- Planned workouts can be delivered to the Wear OS companion path with
  trackable sync status.

## Data and Deletion Requirements

Any new user-scoped table must:

- reference the user identity row with `ON DELETE CASCADE`;
- be included in future export flows;
- be deletable by user ID;
- avoid singleton assumptions;
- avoid storing secrets in plaintext;
- use bounded enum-like values where labels may become metrics.

New mobile and wearable integration tables must also:

- store credentials or device linkage state encrypted at rest where applicable;
- remain user-scoped rather than process-scoped;
- avoid embedding provider-specific SDK assumptions into coaching-domain
  tables.

Do not add metrics with unbounded labels such as user ID, date, activity ID, or
Garmin workout ID.

## Testing Strategy

Unit tests:

- API-key hashing and lookup.
- Secret encryption/decryption and invalid-key failure.
- User preference fallback behavior.
- Locale fallback and user-facing copy language selection.
- User-scoped history queries.
- `create_for_user()` dependency construction.

API tests:

- user creation returns a one-time API key;
- authenticated `GET /v1/me`;
- unauthorized requests fail;
- one user's API key cannot access another user's records;
- preference updates feed scheduler/orchestrator behavior.
- global LLM settings can be read and patched through `/admin/llm-settings`;
- user LLM overrides can be set and cleared through
  `/admin/users/{user_id}/llm-settings`;
- effective LLM settings resolve as user override, then global default, then
  deployment fallback;
- missing or invalid admin API keys fail with 401/403;
- regular user API keys cannot access `/admin/*`.

Planner tests:

- `llm_driven` planning passes the effective selected model into the Gemini
  client call;
- `legacy` planning remains unaffected by LLM model setting changes.

Integration tests:

- Postgres schema bootstrap with new tables.
- Docker service startup for a target user ID.
- A targeted `auto` run with persisted sync state.

Future mobile ecosystem tests:

- Apple ecosystem integration state can be stored and loaded per user.
- Android ecosystem integration state can be stored and loaded per user.
- Provider-normalized activity and recovery payloads can enter the same
  coaching pipeline without Garmin-specific assumptions.
- Workout delivery status can be tracked per provider target without mutating
  unrelated providers.

When changes affect Garmin uploads, Google Calendar sync, scheduling, or
database persistence, verify with the Docker stack before reporting completion.

## Non-Goals for the First MVP

- Building the mobile app UI.
- Building the watchOS app or Wear OS app.
- Full email/password account login.
- User-owned LLM API keys.
- External KMS integration.
- HealthKit, Health Connect, or Google Fit ingestion in the first multi-user
  MVP.
- Rewriting coaching rules or planner behavior.
- Rewriting the Garmin pipeline just to make mobile expansion possible.
- Fully renaming every internal `athlete` symbol in one pass.
- Multi-user DB polling scheduler in a single process.

## Implementation Defaults

Use these defaults unless a later plan explicitly overrides them:

- Public term: `user`.
- Auth: per-user API key.
- Default locale: Korean for compatibility until the user sets a preference.
- LLM key owner: service.
- Secret storage: encrypted Postgres payloads.
- Scheduler model: one user per worker container.
- Planner behavior: preserve current `legacy` and `llm_driven` semantics.
- Compatibility: keep existing CLI and `.env` path working during migration.
- Android health platform default: `Health Connect`.
- Google Fit role: compatibility and migration path, not the default Android
  target.
- Garmin role: supported long-term provider alongside Apple and Android native
  ecosystems.
