"""Multi-user worker tests."""

from __future__ import annotations

from types import SimpleNamespace

from running_coach.application.user_worker import MultiUserWorker
from running_coach.models.llm_settings import LLMSettings
from running_coach.models.user import UserContext


def _context(user_id: str, external_key: str) -> UserContext:
    return UserContext(
        user_id=user_id,
        external_key=external_key,
        display_name=None,
        garmin_email=f"{external_key}@example.com",
        timezone="Asia/Seoul",
        locale="ko",
        schedule_times="05:00,17:00",
        include_strength=False,
        llm_settings=LLMSettings(
            planner_mode="legacy",
            llm_provider="gemini",
            llm_model="gemini-2.5-flash",
        ),
    )


class FakeUserApp:
    def __init__(self):
        self.contexts = [
            _context("user-1", "runner-1"),
            _context("user-2", "runner-2"),
            _context("user-3", "runner-3"),
        ]
        self.calls: list[tuple[str, str]] = []

    def list_runnable_user_contexts(self):
        return self.contexts

    def run_user_sync(self, user_id: str, run_mode: str = "auto"):
        self.calls.append((user_id, run_mode))
        if user_id == "user-2":
            raise RuntimeError("reauth required")
        if user_id == "user-3":
            return SimpleNamespace(status="skipped", mode=run_mode)
        return SimpleNamespace(status="completed", mode=run_mode)


def test_multi_user_worker_isolates_per_user_failures():
    user_app = FakeUserApp()
    worker = MultiUserWorker(user_app=user_app)  # type: ignore[arg-type]

    summary = worker.run_all(run_mode="auto")

    assert summary.total == 3
    assert summary.completed == 1
    assert summary.failed == 1
    assert summary.skipped == 1
    assert user_app.calls == [
        ("user-1", "auto"),
        ("user-2", "auto"),
        ("user-3", "auto"),
    ]
    assert summary.results[1].error == "reauth required"
