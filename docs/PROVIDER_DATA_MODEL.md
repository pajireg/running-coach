# Provider Data Model

Running Coach supports Garmin today and must later support Apple Watch +
iPhone, watchOS, Wear OS, HealthKit, Health Connect, and Google Fit without
turning provider payload differences into application-wide conditionals.

## Decision

The product data model is canonical-first:

- Store normalized fields that coaching, API responses, exports, and deletion
  flows need directly on domain tables.
- Store provider identity separately as `provider` plus a provider-native
  external id such as `provider_activity_id`.
- Store workout delivery state as provider-neutral delivery fields:
  `delivery_provider`, `external_workout_id`, and `delivery_status`.
- Keep provider adapters responsible for converting source payloads into the
  canonical model.

## Raw Payload Policy

Raw provider payloads are not the long-term product model.

Existing `raw_payload` fields remain for compatibility and short-term
diagnostics, but new product behavior should not depend on reading provider raw
JSON. If raw ingestion auditing becomes necessary, add a separate ingestion
event store with an explicit retention policy instead of expanding domain
tables around provider-specific JSON.

When a provider-specific value becomes useful for coaching or app UX, promote it
to a normalized column or a typed observation model after defining how it maps
across providers.

## Current Canonical Fields

Activities use:

- `provider`
- `provider_activity_id`
- `activity_date`
- `started_at`
- `sport_type`
- `distance_km`
- `duration_seconds`
- `avg_pace`
- `avg_hr`
- `max_hr`
- `elevation_gain_m`
- `calories`

Planned workout delivery uses:

- `delivery_provider`
- `external_workout_id`
- `delivery_status`

Garmin remains the default concrete provider, but it is now represented as the
value `garmin` inside provider-neutral fields.
