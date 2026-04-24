# Mobile App Handoff

This document is the implementation handoff for a mobile app agent. It reflects
the current backend state and should be treated as the source of truth for the
first app slice.

## Product Direction

Running Coach is being refactored into a multi-user, multi-provider product.
The mobile app should support iPhone and Android users while keeping Garmin
Connect as a first-class provider.

Important product assumptions:

- iPhone users may still use Garmin devices.
- Android users may still use Garmin devices.
- Apple HealthKit, Health Connect, and Google Fit are planned providers, but
  concrete backend sync adapters are not implemented yet.
- Garmin Connect currently remains the only real training-data and workout
  delivery provider.
- The mobile app should consume provider-neutral concepts such as provider,
  status, capabilities, plan, activity, and schedule.

## Current Backend Status

The backend currently exposes enough API surface for an initial app shell:

- user profile;
- app dashboard summary;
- provider integration inventory;
- preference updates;
- manual sync trigger;
- coaching input mutations for feedback, availability, goals, blocks, and
  injuries.

This is not yet a production mobile backend. The biggest missing pieces are
real mobile auth, credential registration flows, and native HealthKit/Health
Connect ingestion.

## Authentication

Current auth is a development bearer API key:

```http
Authorization: Bearer <apiKey>
```

The app agent should not implement production login, signup, refresh tokens,
social login, biometric login, or account recovery yet.

For local development, a user can be created through `POST /v1/users`, which
returns a one-time `apiKey`. Treat this as temporary.

## Initial App Scope

Build these screens first:

- Home dashboard: consume `GET /v1/me/dashboard`.
- Integration status: consume `GET /v1/me/integrations`.
- Preferences/settings: consume `GET /v1/me` and `PATCH /v1/me/preferences`.
- Daily feedback input: submit `POST /v1/me/feedback`.
- Availability editor: submit `POST /v1/me/availability`.
- Goal editor: submit `POST /v1/me/goals`.
- Injury status input: submit `POST /v1/me/injuries`.

Do not build native HealthKit or Health Connect sync screens beyond passive
`coming_soon` display states unless the backend contract is extended.

## Implemented API

All user routes are under `/v1`.

### `POST /v1/users`

Creates a development user and returns a one-time API key.

Request:

```json
{
  "displayName": "Runner One",
  "garminEmail": "runner@example.com",
  "timezone": "Asia/Seoul",
  "locale": "ko",
  "scheduleTimes": "05:00,17:00",
  "runMode": "auto",
  "includeStrength": false
}
```

Response:

```json
{
  "apiKey": "rcu_example",
  "user": {
    "userId": "user-uuid",
    "externalKey": "runner-1",
    "displayName": "Runner One",
    "garminEmail": "runner@example.com",
    "preferences": {
      "timezone": "Asia/Seoul",
      "locale": "ko",
      "scheduleTimes": "05:00,17:00",
      "runMode": "auto",
      "includeStrength": false
    },
    "llmSettings": {
      "plannerMode": "legacy",
      "llmProvider": "gemini",
      "llmModel": "gemini-2.5-flash"
    },
    "integrationStatus": {
      "garmin": "configured",
      "googleCalendar": "env_compat"
    }
  }
}
```

### `GET /v1/me`

Returns the current user profile.

Use this for settings/profile display.

Key fields:

- `preferences.timezone`
- `preferences.locale`
- `preferences.scheduleTimes`
- `preferences.runMode`
- `preferences.includeStrength`
- `integrationStatus.garmin`
- `integrationStatus.googleCalendar`

### `GET /v1/me/dashboard`

Returns app-home data in one request.

Response shape:

```json
{
  "user": {
    "userId": "user-uuid",
    "externalKey": "runner-1",
    "displayName": "Runner One",
    "garminEmail": "runner@example.com",
    "preferences": {
      "timezone": "Asia/Seoul",
      "locale": "ko",
      "scheduleTimes": "05:00,17:00",
      "runMode": "auto",
      "includeStrength": false
    },
    "llmSettings": {
      "plannerMode": "legacy",
      "llmProvider": "gemini",
      "llmModel": "gemini-2.5-flash"
    },
    "integrationStatus": {
      "garmin": "configured",
      "googleCalendar": "env_compat"
    }
  },
  "schedule": {
    "nextRunAt": "2026-04-24T20:00:00Z",
    "lastRunAt": null,
    "lastStatus": null,
    "lastError": null,
    "failureCount": 0,
    "nextRetryAt": null,
    "disabledAt": null,
    "leaseUntil": null
  },
  "currentPlan": [
    {
      "date": "2026-04-25",
      "workoutName": "Base Run",
      "sessionType": "base",
      "workoutType": "Base Run",
      "plannedMinutes": 45,
      "isRest": false
    }
  ],
  "recentActivities": [
    {
      "provider": "garmin",
      "providerActivityId": "activity-1",
      "activityDate": "2026-04-24",
      "startedAt": "2026-04-24T06:30:00+09:00",
      "title": "Morning Run",
      "sportType": "Running",
      "distanceKm": 8.1,
      "durationSeconds": 2700,
      "avgPace": "5:33",
      "avgHr": 145,
      "plannedWorkoutName": "Base Run",
      "executionStatus": "completed",
      "executionQuality": "normal",
      "targetMatchScore": 0.9
    }
  ]
}
```

Empty states are valid:

- `currentPlan: []`
- `recentActivities: []`
- schedule timestamps may be `null`.

### `GET /v1/me/integrations`

Returns provider-neutral integration inventory. This endpoint must be used for
the app's integration/status screen.

Response shape:

```json
{
  "integrations": [
    {
      "provider": "garmin",
      "displayName": "Garmin Connect",
      "status": "env_compat",
      "connected": true,
      "source": "env_compat",
      "capabilities": ["training_data", "workout_delivery"],
      "lastError": null
    },
    {
      "provider": "google_calendar",
      "displayName": "Google Calendar",
      "status": "env_compat",
      "connected": true,
      "source": "env_compat",
      "capabilities": ["calendar_sync"],
      "lastError": null
    },
    {
      "provider": "healthkit",
      "displayName": "Apple HealthKit",
      "status": "coming_soon",
      "connected": false,
      "source": "planned",
      "capabilities": ["health_data", "activity_data"],
      "lastError": null
    },
    {
      "provider": "health_connect",
      "displayName": "Health Connect",
      "status": "coming_soon",
      "connected": false,
      "source": "planned",
      "capabilities": ["health_data", "activity_data"],
      "lastError": null
    },
    {
      "provider": "google_fit",
      "displayName": "Google Fit",
      "status": "coming_soon",
      "connected": false,
      "source": "planned",
      "capabilities": ["activity_data"],
      "lastError": null
    }
  ]
}
```

Known provider values:

- `garmin`
- `google_calendar`
- `healthkit`
- `health_connect`
- `google_fit`

Known status values:

- `active`
- `configured`
- `env_compat`
- `reauth_required`
- `disabled`
- `error`
- `not_configured`
- `coming_soon`

Known source values:

- `db`
- `env_compat`
- `profile`
- `none`
- `planned`

The app must never expect credential payloads or tokens from this endpoint.

### `PATCH /v1/me/preferences`

Updates user-visible preferences.

Request fields are optional:

```json
{
  "displayName": "Updated Runner",
  "garminEmail": "runner@example.com",
  "timezone": "Asia/Seoul",
  "locale": "ko",
  "scheduleTimes": "05:00,17:00",
  "runMode": "auto",
  "includeStrength": false
}
```

Supported `runMode` values:

- `auto`
- `plan`

Avoid exposing `plannerMode`, `llmProvider`, and `llmModel` in the first mobile
UI unless the product explicitly wants advanced/debug controls.

### `POST /v1/runs/sync`

Triggers a user-scoped sync run.

Request:

```json
{
  "mode": "auto"
}
```

Supported `mode` values:

- `auto`
- `plan`

Use this as a manual development/debug action only. Do not build an aggressive
polling or repeated sync UX.

### `POST /v1/me/feedback`

Records daily subjective feedback.

Request:

```json
{
  "feedbackDate": "2026-04-25",
  "fatigueScore": 6,
  "sorenessScore": 4,
  "stressScore": 5,
  "motivationScore": 7,
  "sleepQualityScore": 6,
  "painNotes": "Left calf tightness",
  "notes": "Busy day"
}
```

Score fields are optional, but when present they must be integers from 1 to 10.

### `POST /v1/me/availability`

Updates one weekday availability rule.

Request:

```json
{
  "weekday": 2,
  "isAvailable": true,
  "maxDurationMinutes": 45,
  "preferredSessionType": "quality"
}
```

`weekday` uses Python convention:

- `0` Monday
- `1` Tuesday
- `2` Wednesday
- `3` Thursday
- `4` Friday
- `5` Saturday
- `6` Sunday

### `POST /v1/me/goals`

Upserts an active race goal.

Request:

```json
{
  "goalName": "10K PB",
  "raceDate": "2026-09-20",
  "distance": "10K",
  "goalTime": "49:00",
  "targetPace": "4:54",
  "priority": 1,
  "isActive": true
}
```

### `POST /v1/me/blocks`

Upserts a training block.

Request:

```json
{
  "phase": "build",
  "startsOn": "2026-04-27",
  "endsOn": "2026-06-07",
  "focus": "10K preparation",
  "weeklyVolumeTargetKm": 45.0
}
```

### `POST /v1/me/injuries`

Upserts injury status.

Request:

```json
{
  "statusDate": "2026-04-25",
  "injuryArea": "calf",
  "severity": 3,
  "notes": "Mild tightness",
  "isActive": true
}
```

`severity` must be an integer from 0 to 10.

## Recommended App UX

Home screen:

- show next scheduled backend run from `schedule.nextRunAt`;
- show current planned workouts from `currentPlan`;
- show recent completed activities from `recentActivities`;
- show an empty state when no plan or activity exists yet;
- avoid implying HealthKit or Health Connect sync is active.

Integrations screen:

- render every item from `/v1/me/integrations`;
- use `connected` as the primary UI boolean;
- show `reauth_required` and `error` as attention states;
- show `coming_soon` as disabled/planned provider state;
- do not ask for Garmin/Google credentials yet because backend write APIs are
  not implemented.

Settings screen:

- allow display name, timezone, locale, schedule times, run mode, and strength
  inclusion to be edited;
- do not expose LLM provider/model controls in the first consumer UI;
- explain schedule times as backend coaching check-in times, not phone push
  notification times.

Feedback screen:

- submit one daily feedback payload;
- keep fields optional;
- validate score range client-side before submit.

## Do Not Build Yet

Do not implement these flows until backend support is added:

- production login/session/refresh-token flow;
- Garmin credential registration, deletion, or reauth flow;
- Google OAuth flow;
- HealthKit data upload;
- Health Connect data upload;
- Google Fit data upload;
- push notifications;
- in-app payments/subscriptions;
- LLM provider/model selector for normal users;
- workout editing or provider workout upload from the mobile app.

## Backend Boundaries

The app should treat the backend as API-first and user-scoped.

Do not rely on:

- Garmin workout titles for identity;
- provider-specific activity ids without the `provider` field;
- raw provider payloads;
- a fixed timezone;
- fixed check-in times;
- a singleton user;
- `05:00,17:00` as a global rule.

Do rely on:

- bearer API key only for current development builds;
- provider-neutral `provider` values;
- `currentPlan` and `recentActivities` as display summaries;
- `schedule.nextRunAt` as the next backend scheduling time;
- `/v1/me/integrations` as the source of truth for integration display.

## Suggested First Milestone

Build a local app prototype with:

1. API-key entry screen.
2. Home dashboard screen.
3. Integrations/status screen.
4. Settings/preferences screen.
5. Daily feedback submission screen.

After that, request backend support for:

1. production auth;
2. Garmin credential connect/disconnect;
3. native health data ingestion contract for HealthKit and Health Connect;
4. push notification preferences.
