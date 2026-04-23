# Coaching Architecture

English | [한국어](COACHING_ARCHITECTURE.ko.md)

## Goal

Running Coach is designed as an always-on coaching backend that accumulates athlete history, estimates training state, produces explainable plans, and synchronizes those plans into execution systems such as Garmin Connect and Google Calendar.

This document explains the runtime shape of the system, the responsibilities of each major module, and the architectural boundaries between data collection, state storage, planning, and presentation.

## Runtime Model

The default deployment model is Docker-based and intended to run continuously.

### Main runtime services

- `postgres`
  - durable coaching-history and state database
- `garmin-coach`
  - ingestion, planning, Garmin sync, Google Calendar sync, and internal scheduling

## High-Level Flow

1. Load environment configuration and athlete settings
2. Authenticate Garmin and optional Google Calendar
3. Collect health, performance, activity, calendar, and constraint context
4. Normalize and persist state into Postgres
5. Rebuild planned-vs-actual execution links
6. Summarize coaching state and build CoachingContext
7. Dispatch to the active planner (`legacy` or `llm_driven` per `COACH_PLANNER_MODE`)
8. For `llm_driven`: render prompt, call Gemini, parse JSON, run SafetyValidator auto-correction
9. For `legacy`: build a rule-based skeleton, deterministic steps, and deterministic descriptions
10. Save plans and coach-decision rationale
11. Upload workouts to Garmin (skip Rest Days) and sync Google Calendar

## Architectural Layers

### 1. Ingestion layer

Responsible for talking to external systems and pulling raw state into the application.

Main modules:

- `src/running_coach/clients/garmin/`
- `src/running_coach/clients/google_calendar/`

Responsibilities:

- Garmin login and token management
- health and performance collection
- recent activity and lap retrieval
- scheduled workout history retrieval
- Garmin workout upload and scheduling
- Google Calendar event creation and update

### 2. Normalization and persistence layer

Responsible for turning raw external payloads into durable internal state.

Main modules:

- `src/running_coach/storage/history_service.py`
- `src/running_coach/storage/database.py`

Responsibilities:

- athlete upsert
- daily metrics persistence
- activity and lap persistence
- planned-workout persistence
- planned-vs-actual linkage
- coaching-state summarization
- coach-decision logging

### 3. Planning layer

Responsible for translating stored state into a safe, explainable weekly plan.

Main modules:

- `src/running_coach/coaching/context.py` — `CoachingContextBuilder` assembles scores, pace capability profile, execution history, injuries, feedback, availability, training background into a `CoachingContext` dataclass
- `src/running_coach/coaching/prompt.py` — `LLMPromptTemplate` renders the context as a deterministic Korean prompt (prompt-cache friendly, no threshold leakage)
- `src/running_coach/coaching/safety/` — 15 safety rules + `SafetyValidator` with multi-pass auto-correction
- `src/running_coach/coaching/planners/` — `Planner` protocol, `LegacySkeletonPlanner`, `LLMDrivenPlanner`
- `src/running_coach/clients/gemini/planner.py` — legacy skeleton calculation utility

Responsibilities (by path):

- `context.py`: turn raw history_service output into a typed context (chronic load, raw 14-day execution rows, staleness-tagged feedback, etc.)
- `prompt.py`: emit a structured prompt including a training catalog (Interval, Threshold, Tempo Run, Fartlek, Long Run, Base Run, Recovery Run, Rest Day)
- `safety/`: enforce hard constraints (date starts today, user-policy long-run cap, no back-to-back quality, injury blocks, ACWR cap, user-policy minimum rest, pace safety bands, workout name standardization, etc.) with auto-correction
- `planners/llm_driven.py`: pipeline `CoachingContext → prompt → Gemini → Pydantic → SafetyValidator`; falls back to `LegacySkeletonPlanner` on parse/quota/unresolvable errors
- `clients/gemini/planner.py`: skeleton-building utility reused by `LegacySkeletonPlanner`

### 4. Orchestration layer

Responsible for the end-to-end workflow and fault boundaries between subsystems.

Main module:

- `src/running_coach/core/orchestrator.py`

Responsibilities:

- sequence ingestion, persistence, planning, upload, and calendar sync
- keep partial failures from corrupting planning history
- save explainable state snapshots and decision rationale

## Database Responsibilities

The database is the canonical application state store.

### Core tables

- `athletes`
  - athlete identity and profile
- `daily_metrics`
  - daily recovery, training-state, and load snapshots
- `activities`
  - normalized completed activities
- `activity_laps`
  - lap and split detail for execution-quality analysis
- `planned_workouts`
  - future prescription history
- `workout_executions`
  - planned-vs-actual linkage and execution interpretation
- `subjective_feedback`
  - fatigue, soreness, stress, motivation, and sleep-quality input
- `injury_status`
  - active injury constraints and severity
- `availability_rules`
  - weekday constraints and preferences
- `training_blocks`
  - base, build, peak, and taper phase data
- `race_goals`
  - race target data
- `coach_decisions`
  - explainable planning snapshots and rationale

## External System Boundaries

### Garmin Connect

Role:

- source of device-derived health, performance, and activity data
- destination for scheduled workouts

Important boundary:

- Garmin is a source of sensor and execution data, not the canonical internal state store
- scheduled workouts are tracked by stored Garmin workout IDs when possible, so user-facing workout titles can stay short without the `Running Coach:` prefix

### Google Calendar

Role:

- user-facing presentation layer

Current calendars:

- `Running Coach`
  - future planned sessions
- `Workout`
  - completed sessions only

Important boundary:

- Google Calendar is not the source of truth
- calendar events are projections of DB state

### Postgres

Role:

- canonical state store for coaching history
- planning memory
- execution memory
- decision rationale

## Planning Boundary: Rules vs LLM

The boundary depends on `COACH_PLANNER_MODE`.

### `llm_driven` mode (new default target)

**Algorithm owns (hard bounds)**:

- readiness / fatigue / injury scoring (`history_service`)
- pace capability profile and safety bands from LT / PR / race target
- replan-trigger detection (`summarize_plan_freshness`)
- safety rules enforced via `SafetyValidator`:
  - plan starts today
  - active injury severity ≥ 6 → no quality, volume × 0.65
  - active injury severity 3–5 → no intervals, volume × 0.85
  - long_run count capped by `CoachingContext.plan_policy`
  - long_run must use user-preferred long-run availability dates when present
  - no back-to-back hard sessions
  - no quality the day after long run
  - quality sessions ≥ 48h apart
  - hard-session count capped by `CoachingContext.plan_policy`
  - respect availability / max duration / policy minimum rest days
  - 7-day km / chronic-7d ACWR capped by `CoachingContext.plan_policy`
  - step pace must stay inside the relevant pace safety band
  - non-rest days must have valid steps with ≥ 60s per step
  - workout name standardization by session type + step structure

**LLM owns (judgment)**:

- session type placement across 7 days
- 7-day horizon volume target
- planned minutes per day
- step structure (warmup/run/interval/recovery/cooldown layout)
- concrete target pace within the safety bands
- phase interpretation (base / build / peak / taper)
- Korean rationale and risk acknowledgements
- training variety selection (Interval vs Threshold vs Tempo vs Fartlek based on athlete state)

When the LLM output violates a safety rule, the validator auto-corrects and logs the violation. Unresolvable plans fall back to `LegacySkeletonPlanner`.

### `legacy` mode (fallback, default until `llm_driven` burn-in completes)

The legacy path builds a rule-based skeleton in `planner._build_weekly_skeleton`, then uses `StepTemplateEngine` and `DescriptionRenderer` to fill workout steps and Korean descriptions without Gemini calls.

This separation keeps the system explainable and reduces unsafe plan drift.

## Scheduler and Operational Timing

Service schedules are configurable. A user can run one or more daily check-ins, for example `05:00,17:00`, through `--times` or `COACH_SCHEDULE_TIMES` in Docker.

Reasoning:

- plans should be ready before early-morning training
- completed activities from the previous day can be incorporated at that time
- future workouts can be refreshed before the athlete checks Garmin
- real-world users may train before work, after work, or irregularly, so the scheduler must not assume a single fixed routine

Operational policy:

- service mode normally runs in `auto` mode
- each run first reconciles Garmin, database, and calendar state
- the LLM is called only when an active plan is missing, a new activity appeared after the last plan, recovery metrics materially worsened after the last plan, a key workout was missed, or base-volume misses accumulated
- a single missed recovery run is treated as extra rest and does not replan by itself
- overdue planned-workout checks only consider dates before the current `as_of` date, so an afternoon check-in does not mark a same-day evening workout as missed
- completed-activity calendar sync is incremental
- large historical backfills are manual, not part of the daily loop

## Failure and Consistency Principles

The system is designed to degrade gracefully.

### Current principles

- plan generation failure must not erase existing future workouts
- calendar-sync failure must not erase DB history
- upload or calendar issues should be isolated from ingestion and state persistence
- normalized DB rows should exist even if external sync partially fails

## Current Strengths

- live Garmin execution loop works end to end
- coaching decisions are persisted and explainable
- planned-vs-actual interpretation feeds back into next-week planning
- Google Calendar clearly separates future plans and completed activities
- cross-training load and Garmin-native load are both incorporated
- workout pace targets are personalized through deterministic center paces in `legacy` mode and LLM-selected paces inside safety bands in `llm_driven` mode

## Current Limits

- athlete-specific personalization still improves as more history accumulates
- session-quality interpretation can still be refined further
- product-level UI is still minimal
- operational observability and reporting are still lightweight

## Recommended Next Steps

1. Add richer reporting and dashboards on top of `coach_decisions`
2. Continue refining session-quality interpretation from laps, pace, and HR drift
3. Improve athlete-specific adaptation from longer execution history
4. Add stronger retry, monitoring, and sync-state visibility
