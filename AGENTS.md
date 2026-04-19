# Repository Guidelines

## Project Structure & Module Organization
Application code lives in `src/running_coach/`. Keep orchestration and scheduling in `core/`, external integrations in `clients/`, Pydantic contracts in `models/`, settings/constants in `config/`, persistence in `storage/`, and shared helpers in `utils/`. Database bootstrap SQL lives in `db/init/`, operational docs in `docs/`, and auth/bootstrap scripts in `scripts/`. Tests are under `tests/unit/`, grouped by area such as `clients/`, `core/`, and `storage/`.

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

Docker defaults use `COACH_SCHEDULE_TIMES=05:00,17:00` and `COACH_SERVICE_RUN_MODE=auto`.

## Coding Style & Naming Conventions
Target Python 3.10+ with 4-space indentation and a 100-character line limit. Black and Ruff define the formatting baseline; avoid style-only churn outside touched files. Use type hints on public functions and prefer Pydantic models over raw dicts for cross-layer data. Modules/functions use `snake_case`, classes use `PascalCase`, and constants use `UPPER_SNAKE_CASE`. Keep runtime logs and user-facing copy in Korean.

## Testing Guidelines
Pytest discovers `test_*.py` under `tests/` and collects coverage for `src/running_coach`. Add focused unit tests beside the touched area, for example `tests/unit/storage/test_history_service.py` or `tests/unit/clients/test_calendar_sync.py`. Use `pytest -k "pattern"` for targeted runs and `pytest --no-cov` for faster iteration when coverage output is not needed.

## Commit & Pull Request Guidelines
Use Conventional Commits such as `feat: ...`, `fix: ...`, or `refactor: ...`; concise Korean subjects are acceptable. Keep commits logically grouped and include a message body when the change spans runtime flow, storage, or sync behavior. PRs should summarize user-visible changes, note verification commands, and include screenshots or sample logs when Garmin/Google Calendar behavior changes.

## Security & Configuration Tips
Do not commit `.env`, `.garmin_tokens/`, or Google credential/token JSON files such as `.google/credentials.json` and `.google/token_google.json`. The `.google/` directory may be tracked with a placeholder such as `.gitkeep`. Treat Garmin and Google tokens as local secrets. Wire new services through `core/container.py` so orchestration, testing, and Docker behavior stay consistent.

## Agent-Specific Operating Rules
For changes that affect Garmin uploads, Google Calendar sync, scheduling, or database persistence, verify behavior with the Docker stack before reporting completion. Prefer `docker-compose up -d --build`, `docker-compose exec -T garmin-coach python -m running_coach`, and a targeted Postgres query when sync state changes.

Do not rely on Garmin workout titles for cleanup. Use stored `garmin_workout_id` values from the database whenever possible, because user-facing titles are intentionally concise.

In service mode, do not assume a fixed athlete routine. `05:00,17:00` is only the current user's default. Preserve configurable scheduling through `--times` and `COACH_SCHEDULE_TIMES`.

In `auto` mode, reconcile first and call the LLM only when the active plan is missing, no previous plan decision exists, a new Garmin activity was recorded after the last plan, recovery metrics materially worsened after the last plan, a key workout was missed, or base-volume misses accumulated. Treat a single missed recovery run as extra rest unless other triggers exist. If the plan is fresh, keep existing Garmin workouts and sync only completed activities as needed.

Do not make hard-coded coaching assumptions such as “no long runs on consecutive days.” Use athlete state, recent training load, execution quality, recovery indicators, and training history to decide whether progression, maintenance, or recovery is appropriate.

When changing coaching logic, update `docs/COACHING_ALGORITHM.md`, `docs/COACHING_ALGORITHM.ko.md`, and any README sections that describe user-visible behavior. Keep code and technical docs primarily in English; keep runtime logs and CLI-facing messages in Korean.

Never commit real credentials, OAuth tokens, Garmin tokens, personal activity exports, or local runtime state. Leave `.env`, `.garmin_tokens/`, `.google/*.json`, and generated local data untracked.
