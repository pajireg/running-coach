# Repository Guidelines

## Project Structure & Module Organization
Application code lives in `src/running_coach/`. Keep orchestration and scheduling in `core/`, external integrations in `clients/`, Pydantic contracts in `models/`, settings/constants in `config/`, persistence in `storage/`, coaching logic (context builder, prompt renderer, safety validator, planner dispatcher) in `coaching/`, and shared helpers in `utils/`. Database bootstrap SQL lives in `db/init/`, operational docs in `docs/`, and auth/bootstrap scripts in `scripts/`. Tests are under `tests/unit/`, grouped by area such as `coaching/`, `coaching/safety/`, `coaching/planners/`, `clients/`, `core/`, and `storage/`.

## Build, Test, and Development Commands
Install runtime deps with `pip install -e .`; use `pip install -e ".[dev]"` for linting and tests. Run the app once with `python -m running_coach` or `running-coach`. First-time Garmin auth uses `python scripts/setup_garmin.py`. Start the service stack with `docker-compose up -d`. Main checks:

```bash
pytest
ruff check src tests
black src tests
mypy src
```

Service mode supports configurable check-in times and conditional replanning:

```bash
python -m running_coach run --service --times 05:00,17:00 --mode auto
```

Force a fresh 7-day plan and Garmin workout upload with:

```bash
python -m running_coach run --mode plan
```

Inside Docker, use:

```bash
docker-compose exec -T garmin-coach python -m running_coach run --mode plan
```

Docker defaults use `COACH_SCHEDULE_TIMES=05:00,17:00` and `COACH_SERVICE_RUN_MODE=auto`.

## Coding Style & Naming Conventions
Target Python 3.10+ with 4-space indentation and a 100-character line limit. Black and Ruff define the formatting baseline; avoid style-only churn outside touched files. Use type hints on public functions and prefer Pydantic models over raw dicts for cross-layer data. Modules/functions use `snake_case`, classes use `PascalCase`, and constants use `UPPER_SNAKE_CASE`. Keep runtime logs and user-facing copy in Korean.

## Testing Guidelines
Pytest discovers `test_*.py` under `tests/` and collects coverage for `src/running_coach`. Add focused unit tests beside the touched area, for example `tests/unit/storage/test_history_service.py` or `tests/unit/clients/test_calendar_sync.py`. Use `pytest -k "pattern"` for targeted runs and `pytest --no-cov` for faster iteration when coverage output is not needed.

## Commit & Pull Request Guidelines
Use Conventional Commits such as `feat: ...`, `fix: ...`, or `refactor: ...`; concise Korean subjects are acceptable. Keep commits logically grouped and include a message body when the change spans runtime flow, storage, sync behavior, or coaching contracts. PRs should summarize user-visible changes, note verification commands, and include screenshots or sample logs when Garmin/Google Calendar behavior changes.

## Security & Configuration Tips
Do not commit `.env`, `.garmin_tokens/`, or Google credential/token JSON files such as `.google/credentials.json` and `.google/token_google.json`. The `.google/` directory may be tracked with a placeholder such as `.gitkeep`. Treat Garmin and Google tokens as local secrets. Wire new services through `core/container.py` so orchestration, testing, and Docker behavior stay consistent.

## Agent-Specific Operating Rules
For changes that affect Garmin uploads, Google Calendar sync, scheduling, or database persistence, verify behavior with the Docker stack before reporting completion. Prefer `docker-compose up -d --build`, `docker-compose exec -T garmin-coach python -m running_coach`, and a targeted Postgres query when sync state changes.

Do not rely on Garmin workout titles for cleanup. Use stored `garmin_workout_id` values from the database whenever possible, because user-facing titles are intentionally concise.

In service mode, do not assume a fixed athlete routine. `05:00,17:00` is only the current user's default. Preserve configurable scheduling through `--times` and `COACH_SCHEDULE_TIMES`.

In `auto` mode, the scheduler returns one of three states from `_should_generate_plan()`:

- `skip` — plan is fresh, no triggers fired; keep existing Garmin workouts, sync completed activities only.
- `extend` — athlete completed today's workout normally (`target_match_score >= 0.75`) and the plan is otherwise stable; keep the existing 6 future days and ask the LLM (or algorithm) to generate only 1 new day via `extend_training_plan()`.
- `replan` — full 7-day generation; triggered when the active plan is missing, no prior decision exists, recovery metrics materially worsened, a key workout was missed, or base-volume misses accumulated.

Treat a single missed recovery run as extra rest unless other triggers exist. Never collapse `extend` into `replan` just because a new activity was recorded — check `activity_is_normal_execution` first.

Do not make hard-coded coaching assumptions such as “no long runs on consecutive days.” Use athlete state, recent training load, execution quality, recovery indicators, and training history to decide whether progression, maintenance, or recovery is appropriate.

When changing coaching logic, update `docs/COACHING_ALGORITHM.md`, `docs/COACHING_ALGORITHM.ko.md`, and any README sections that describe user-visible behavior. Keep code and technical docs primarily in English; keep runtime logs and CLI-facing messages in Korean.

Never commit real credentials, OAuth tokens, Garmin tokens, personal activity exports, or local runtime state. Leave `.env`, `.garmin_tokens/`, `.google/*.json`, and generated local data untracked.

## Coaching Architecture Rules

Two planner modes coexist and are selected by `COACH_PLANNER_MODE`:

- `legacy` (default, **free tier**) — `LegacySkeletonPlanner` in `coaching/planners/legacy.py`. Uses `_build_weekly_skeleton` for session placement and volume, then `StepTemplateEngine` + `DescriptionRenderer` for deterministic step structure and Korean description. **No LLM calls.** `QualitySubtypeSelector` picks quality subtype (interval/fartlek/threshold/tempo) from phase + readiness + injury_risk. Pipeline: skeleton → steps → description → `SafetyValidator` (15 rules).
- `llm_driven` (**paid tier**) — `coaching/planners/llm_driven.py` pipes `CoachingContext → prompt → LLM → Pydantic → SafetyValidator`. The LLM decides session placement, weekly volume, duration, step structure, concrete target pace inside safety bands, and phase; the algorithm provides evidence normalization plus hard safety bounds and auto-corrects violations. Supports `extend_plan()` for 1-day extension without full replan.

Both modes require `context_builder` and `safety_validator` at construction time. The `GeminiClient` constructor enforces this; do not make either optional.

When touching coaching logic, respect the following:

- **Algorithm owns**: `readiness/fatigue/injury` scoring (`storage/history_service.py`), `PaceZoneEngine` evidence/profile generation, pace safety bands, replan-trigger detection (`summarize_plan_freshness`), and the 15 rules in `coaching/safety/rules.py` (plan_starts_today, injury blocks, max_one_long_run, no_back_to_back_quality, no_quality_after_long_run, quality_48h_spacing, weekly_hard_cap, respect_unavailability, min_one_rest_per_week, acwr_cap, max_duration_per_day, non_rest_has_steps, injury_reduce_volume, min_step_duration, pace_band_integrity, standardize_workout_name).
- **LLM owns (in `llm_driven`)**: session type per day, weekly volume target, planned minutes, step structure, concrete target pace inside safety bands, phase interpretation (base/build/peak/taper), Korean rationale.
- **Safety rules are hard bounds, not style preferences.** If you add a new rule, expose a `describe(ctx)` string so the LLM sees it in the prompt proactively, and ensure `correct()` converges within `SafetyValidator.max_passes`.
- **ACWR math uses weekly units.** `chronic_ewma_load` is km/day; multiply by 7 before comparing with planned weekly km.
- **Workout naming is enforced post-hoc.** Do not rely on LLM output for workout titles. Use the 8 canonical names: `Rest Day`, `Recovery Run`, `Base Run`, `Interval`, `Threshold`, `Tempo Run`, `Fartlek`, `Long Run`.
- **Rest days skip both Garmin upload and Google Calendar sync.** Use `session_type == "rest"` (not workout-name match alone) to decide skipping.
- **Do not leak hidden decision thresholds into the LLM prompt.** Pass raw facts (scores, execution rows, injuries) and explicit safety bounds only. Interpretation hints are fine; hidden trigger thresholds are not.
- **LLM output is bounded, not blindly trusted.** `PlanStartsToday` rebases dates to today; structural safety rules may change unsafe session types; `PaceBandIntegrity` preserves in-band pace choices and clamps only unsafe paces to the nearest safety-band boundary; `StandardizeWorkoutName` reassigns titles from step structure.

Safety metrics (`coaching/safety/metrics.py`) expose in-process counters: `violation_counter{rule_id,severity}`, `unresolvable_counter`, `plan_generated_counter{mode}`. Tests reset these via `reset_counters_for_test()`.

## Long-Term Direction (Design Constraints)

The codebase is intended to evolve into a multi-user, multi-LLM, multi-client product. Preserve these invariants when adding new code:

- **Multi-tenant first.** `athletes.external_key` already identifies each user. Any new query, service, or background job MUST accept an athlete/user id rather than a singleton. Do not introduce new singleton state keyed on `Settings.garmin_email`.
- **LLM provider abstraction.** `google.genai` is currently imported directly in `clients/gemini/client.py` and `coaching/planners/llm_driven.py`. New LLM features should route through a planned `LLMProvider` protocol. Do not add more direct `genai` calls outside the existing files; if you need another Gemini-only feature, place it behind a clearly named method so it is easy to swap later. Prompts must avoid provider-specific quirks (e.g., Gemini's `response_mime_type`) leaking into coaching modules — keep that concern in the client layer.
- **Per-user configuration belongs in the database, not env vars.** `Settings` is process-global. Any new knob that a user should customize (schedule times, include_strength, coach_planner_mode, preferred LLM, max weekly km, notification preferences) should read from an `athlete_preferences`-style table, falling back to `Settings` defaults. Do not add new `COACH_*` env vars for behavior that should eventually be per-user.
- **Secrets are per-user and encrypted at rest.** The current `.garmin_tokens/` file works only for the single-tenant deployment. New integrations must store credentials/tokens in DB columns with encryption (KMS or app-level), keyed by athlete id. Never design a feature that assumes one shared `.env`.
- **Scheduler must not assume a fixed routine.** Do not hardcode `05:00,17:00` or `Asia/Seoul`. Respect per-user schedule and timezone values from the preferences layer once it lands.
- **API-first.** The CLI is a thin wrapper; treat orchestrator entry points as callable functions that a future HTTP/ASGI layer (FastAPI) can invoke. Do not put business logic in `__main__.py` or CLI parsers.
- **Data portability & deletion.** Any new table must be listed in the export flow and deletable by athlete id. Design schemas with `ON DELETE CASCADE` from `athletes`.
- **LLM cost awareness.** Gate expensive LLM paths behind explicit triggers (replan reasons, user action). Avoid per-minute or per-page LLM calls. Prefer deterministic context ordering so provider-side prompt caching helps.
- **Observability.** Keep metric labels bounded (`rule_id`, `severity`, `mode`). Do not add unbounded labels like `athlete_id`, `date`, `activity_id` to counters; use structured logs or a per-athlete dashboard query instead.
