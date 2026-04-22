# Running Coach

English | [한국어](README.ko.md)

Running Coach is an always-on adaptive running coach built around Garmin Connect data, a Postgres coaching-history database, and a planning engine that supports deterministic rule-based planning plus an optional LLM-driven planner.

It is designed to do more than generate workouts. The system collects athlete history, estimates current training state, explains why a plan was chosen, uploads workouts to Garmin, and syncs both planned and completed sessions to Google Calendar.

## Core Capabilities

- Collect Garmin health, performance, activity, and calendar data
- Persist coaching history, execution history, and decision rationale in Postgres
- Build a 7-day running plan from training load, recovery, race goals, availability, injuries, and subjective feedback
- Incorporate cross-training load from cycling, hiking, strength work, and other non-running sessions
- Interpret planned vs actual execution, including schedule shifts, reduced or excessive stimulus, and unplanned sessions
- Upload workouts to Garmin Connect and schedule them automatically
- Keep Garmin workout titles short, such as `Recovery Run` or `Long Run`
- Sync two Google Calendars:
  - `Running Coach` for future plans
  - `Workout` for completed activities

## System Model

Running Coach is not an LLM-only planner.

The current design is:

1. Garmin and user inputs provide raw state
2. Postgres stores normalized long-term history
3. The active planner builds a safe 7-day plan
4. Safety rules validate and correct the plan before Garmin and calendar sync

The operating principle is:

`Code owns safety bounds and evidence normalization. In llm_driven mode, the LLM owns coaching prescription inside those hard bounds.`

## Quick Start

### 1. Install

```bash
pip install -e .
```

For development tools:

```bash
pip install -e ".[dev]"
```

### 2. Configure Environment

Create a `.env` file in the repository root:

```ini
GARMIN_EMAIL=your_email@example.com
GARMIN_PASSWORD=your_password
GEMINI_API_KEY=your_gemini_api_key

# Optional
MAX_HEART_RATE=197
DATABASE_URL=postgresql://coach:coach@localhost:5432/running_coach
RACE_DATE=2026-05-24
RACE_DISTANCE=10K
RACE_GOAL_TIME=49:00
RACE_TARGET_PACE=4:54
```

### 3. Garmin Authentication

Create Garmin session tokens once:

```bash
python scripts/setup_garmin.py
```

Tokens are stored in `./.garmin_tokens/`.

### 4. Google Calendar Authentication

1. Enable Google Calendar API in Google Cloud Console
2. Create an OAuth Desktop App client
3. Save the downloaded file as `./.google/credentials.json`
4. Run the app once and complete the OAuth flow
5. `./.google/token_google.json` will be created automatically

### 5. Run

One-off execution:

```bash
python -m running_coach
# or
running-coach
```

Force a new 7-day plan and Garmin workout upload:

```bash
python -m running_coach run --mode plan
```

Service mode:

```bash
python -m running_coach run --service --times 05:00,17:00 --mode auto
```

Service schedules are configurable per user. `--times` accepts one or more `HH:MM` values.
Use `--mode plan` when you intentionally want to replace the current future plan with a
fresh 7-day plan. Use `--mode auto` for normal operation: it reconciles
Garmin/DB/Calendar state first, then skips, extends, or replans only when triggers require it.

## CLI Commands

- `python -m running_coach`
  - Collect data, generate a plan, sync Garmin, sync calendars
- `python -m running_coach run --mode plan`
  - Force full 7-day plan generation, delete previously generated future Garmin workouts by stored Garmin workout ID, upload new non-rest workouts, and sync calendars
- `python -m running_coach run --mode auto`
  - Run one reconciliation pass and generate a plan only when the active plan is stale, missing, extendable, or otherwise triggered
- `python -m running_coach run --service --times 05:00,17:00 --mode auto`
  - Run continuously with configurable check-in times and conditional replanning
- `python -m running_coach feedback ...`
  - Store subjective fatigue, soreness, stress, motivation, and sleep-quality input
- `python -m running_coach availability ...`
  - Store weekday availability, preferred workout types, and session-duration limits
- `python -m running_coach goal ...`
  - Store race-goal data
- `python -m running_coach block ...`
  - Store `base / build / peak / taper` block information
- `python -m running_coach injury ...`
  - Store active injury status and severity

## Docker

```bash
docker-compose up -d --build
```

Main services:

- `postgres`
  - durable coaching-history database
- `garmin-coach`
  - ingestion, planning, Garmin sync, and Google Calendar sync

If you use Google Calendar in Docker, keep `./.google/` mounted into the container.

Run a forced plan regeneration inside Docker:

```bash
docker-compose exec -T garmin-coach python -m running_coach run --mode plan
```

Run one conditional reconciliation pass inside Docker:

```bash
docker-compose exec -T garmin-coach python -m running_coach run --mode auto
```

The `python -m ...` part must stay on the same shell command line. If `python` is run by
itself, the container opens a Python prompt instead of executing the CLI.

To use the LLM-driven planner rather than the deterministic legacy planner, set:

```ini
COACH_PLANNER_MODE=llm_driven
```

### Admin LLM Settings

The admin surface is separate from user-facing APIs and requires a deployment
secret:

```ini
ADMIN_API_KEY=change-me
```

Run the admin web app locally with:

```bash
uvicorn running_coach.api.app:create_app --factory --host 0.0.0.0 --port 8000
```

Open `/admin` and enter the admin key. The first page manages global LLM
defaults and per-user overrides for planner mode, provider, and model. Gemini
model changes are applied to the next `llm_driven` plan generation. OpenAI and
Anthropic provider values can be stored for admin configuration, but provider
runtime clients still need to be connected before they can generate plans.

## Quality Checks

```bash
pytest
ruff check src tests
black src tests
mypy src
```

## Repository Layout

```text
src/running_coach/
  clients/          Garmin, Gemini, Google Calendar integrations
  config/           settings and constants
  core/             orchestrator, scheduler, dependency container
  models/           Pydantic models
  storage/          Postgres persistence and coaching history
  utils/            shared utilities
db/init/            Postgres schema bootstrap
docs/               architecture and algorithm documents
scripts/            auth and operational scripts
tests/unit/         unit tests
```

## Documentation

English:

- [Coaching Architecture](docs/COACHING_ARCHITECTURE.md)
- [Coaching Algorithm](docs/COACHING_ALGORITHM.md)

Korean:

- [Coaching Architecture (KO)](docs/COACHING_ARCHITECTURE.ko.md)
- [Coaching Algorithm (KO)](docs/COACHING_ALGORITHM.ko.md)

## Current Coaching Signals

The current coach state combines:

- running volume and run frequency
- cross-training load
- training monotony and strain
- EWMA acute and chronic load
- Garmin-native load signals
  - training status
  - acute load
  - chronic load
  - ACWR
  - load balance
- subjective recovery and fatigue feedback
- race-goal and training-block context
- injury constraints
- planned-vs-actual adherence
- lap-based execution quality

## Current Operating Policy

- `Running Coach` calendar keeps future plans
- `Workout` calendar keeps completed sessions only
- `Workout` sync is incremental for recent actuals
- long historical backfill is treated as a manual operation
- Garmin completed activities are the execution source of truth
- Google Calendar is a presentation and review layer, not the canonical state store

## Security Notes

Do not commit:

- `.env`
- `.garmin_tokens/`
- `.google/`

## Status

The system currently works end to end with live Garmin data, Postgres persistence, Garmin workout upload, and Google Calendar synchronization.

The detailed decision model is documented in [Coaching Algorithm](docs/COACHING_ALGORITHM.md), and the runtime/component view is documented in [Coaching Architecture](docs/COACHING_ARCHITECTURE.md).
