# Agent Instructions

## Shared Vault

Cross-repo coordination and current project state live in the shared Obsidian vault:

`/Users/sumin/Vaults/running-coach`

Start with:

- `README.md`
- `current-state.md`
- `working-agreement.md`
- `20-api/api-contract.md`
- `30-app/app-handoff.md`
- `40-backend/backend-handoff.md`
- `40-backend/repository-guidelines.md`
- `40-backend/agent-operating-rules.md`
- `40-backend/coaching-architecture-rules.md`
- `40-backend/long-term-design-constraints.md`
- `50-operations/runtime-environments.md`

When changing app-visible API behavior, runtime URLs, port mappings, auth behavior, or cross-repo handoff state, update the vault in the same task. Refresh `openapi/openapi.json` after route/schema changes.

Prefer `obsidian-cli` for vault exploration and note operations when available, especially `list`, `print`, `search-content`, `create`, `move`, and `frontmatter`. If the vault is not registered in Obsidian CLI config or the command cannot perform the needed edit, use direct file edits and keep the same vault conventions.

## Repository Basics

Application code lives in `src/running_coach/`. Tests live under `tests/unit/`. Database bootstrap SQL lives in `db/init/`, backend docs in `docs/`, and auth/bootstrap scripts in `scripts/`.

Main checks:

```bash
pytest
ruff check src tests
black src tests
mypy src
```

Prefer focused tests beside touched code. Avoid style-only churn outside touched files. Keep runtime logs and user-facing CLI copy in Korean.

## Non-Negotiables

- Do not commit `.env`, `.garmin_tokens/`, `.google/*.json`, OAuth tokens, Garmin tokens, personal activity exports, or generated local runtime state.
- For Garmin uploads, Google Calendar sync, scheduling, or database persistence changes, verify with the Docker stack before reporting completion.
- Do not rely on Garmin workout titles for cleanup; use stored `garmin_workout_id` values whenever possible.
- Rest days skip both Garmin upload and Google Calendar sync; use `session_type == "rest"`.
- Preserve configurable scheduling through `--times`, `COACH_SCHEDULE_TIMES`, and per-user preferences. Do not hardcode `05:00,17:00` or `Asia/Seoul`.
- In `auto` mode, preserve the `skip`, `extend`, and `replan` distinction. Never collapse `extend` into `replan` just because a new activity was recorded; check `activity_is_normal_execution` first.
- Treat safety rules as hard bounds. If adding a safety rule, expose `describe(ctx)` and ensure correction converges within `SafetyValidator.max_passes`.
- Preserve multi-user design: new queries, services, and jobs should accept `user_id`; do not introduce singleton user assumptions.
- User-customizable behavior belongs in `user_preferences` with `Settings` fallback, not new process-global env vars.
- Do not add new direct `google.genai` calls outside the existing Gemini client/planner files; route new LLM work behind provider abstractions or clearly named client-layer methods.
- Keep metric labels bounded. Do not add unbounded labels like `user_id`, `date`, or `activity_id` to counters.

## Coaching Changes

When changing coaching logic, also update `docs/COACHING_ALGORITHM.md`, `docs/COACHING_ALGORITHM.ko.md`, and any README sections that describe user-visible behavior. Keep code and technical docs primarily in English.

Planner and architecture details live in:

`/Users/sumin/Vaults/running-coach/40-backend/coaching-architecture-rules.md`

Long-term product constraints live in:

`/Users/sumin/Vaults/running-coach/40-backend/long-term-design-constraints.md`
