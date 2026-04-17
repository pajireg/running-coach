# Coaching Architecture

## Goal
Turn `coach-gemini` from a daily plan generator into an always-on coaching system that accumulates athlete history, estimates state, and generates explainable plans.

## Runtime
- `postgres`: long-term storage for athlete history and coach decisions
- `garmin-coach`: ingestion, planning, Garmin sync, and calendar sync
- Docker is the default deployment mode; the app should run continuously and schedule jobs internally

## Data Flow
1. Load athlete settings and connect to Postgres.
2. Pull Garmin daily metrics, recent activities, and historical context.
3. Persist normalized daily state into `daily_metrics` and related tables.
4. Build a coaching state:
   - readiness
   - fatigue
   - injury risk
   - recent volume trend
5. Generate a draft weekly plan.
6. Ask the LLM to explain and refine within hard constraints.
7. Save plan + rationale to Postgres.
8. Upload Garmin workouts and optionally sync Google Calendar.

## Database Responsibilities
- `athletes`: athlete identity and durable profile
- `daily_metrics`: recovery and training state snapshots
- `activities` / `activity_laps`: execution history
- `planned_workouts`: future prescription history
- `workout_executions`: planned vs actual linkage
- `subjective_feedback`: fatigue, soreness, motivation, pain
- `injury_status`: active constraints
- `training_blocks`: base/build/peak/taper phases
- `coach_decisions`: explainable decision log
- `llm_interactions`: prompt/response audit trail

## Design Rules
- Raw API snapshots should never be the only source of truth. Store normalized rows plus JSON payloads.
- Hard coaching constraints live in code, not only in prompts.
- LLM output should be auditable and bounded by schema validation.
- Planning must be resilient: DB or calendar failures should not erase Garmin history or future plans.

## Next Implementation Steps
1. Add Garmin activity ingestion into `activities` and `activity_laps`.
2. Add subjective feedback input channel (web form, Telegram bot, or CLI prompt).
3. Implement a rule-based state estimator using the stored history.
4. Link actual completed workouts back to planned sessions.
5. Build a dashboard for recent load, recovery, and coach rationale.
