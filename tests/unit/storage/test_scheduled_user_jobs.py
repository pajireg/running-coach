"""Scheduled user job service tests."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from running_coach.storage.scheduled_user_jobs import ScheduledUserJobService


class QueryCaptureScheduledJobs(ScheduledUserJobService):
    def __init__(self):
        super().__init__(db=object())  # type: ignore[arg-type]
        self.last_query = ""
        self.last_params: dict[str, Any] = {}

    def _fetchall(self, query: str, params: dict[str, Any]):  # type: ignore[override]
        self.last_query = query
        self.last_params = params
        return [
            {
                "user_id": "user-1",
                "external_key": "runner-1",
                "display_name": "Runner One",
                "garmin_email": "runner@example.com",
                "timezone": "Asia/Seoul",
                "locale": "ko",
                "schedule_times": "05:00,17:00",
                "run_mode": "auto",
                "include_strength": False,
                "planner_mode": None,
                "llm_provider": None,
                "llm_model": None,
                "next_run_at": datetime(2026, 4, 24, 8, 0, tzinfo=timezone.utc),
            }
        ]


def test_compute_next_run_at_uses_user_timezone_and_future_slot():
    service = ScheduledUserJobService(db=object())  # type: ignore[arg-type]

    next_run_at = service.compute_next_run_at(
        timezone_name="Asia/Seoul",
        schedule_times="05:00,17:00",
        now=datetime(2026, 4, 24, 7, 59, tzinfo=timezone.utc),
    )

    assert next_run_at == datetime(2026, 4, 24, 8, 0, tzinfo=timezone.utc)


def test_compute_next_run_at_rolls_to_next_day_after_last_slot():
    service = ScheduledUserJobService(db=object())  # type: ignore[arg-type]

    next_run_at = service.compute_next_run_at(
        timezone_name="Asia/Seoul",
        schedule_times="05:00,17:00",
        now=datetime(2026, 4, 24, 8, 1, tzinfo=timezone.utc),
    )

    assert next_run_at == datetime(2026, 4, 24, 20, 0, tzinfo=timezone.utc)


def test_claim_due_users_uses_due_index_and_skip_locked_query():
    service = QueryCaptureScheduledJobs()

    jobs = service.claim_due_users(
        deployment_garmin_email="runner@example.com",
        worker_id="worker-1",
        batch_size=10,
        now=datetime(2026, 4, 24, 8, 0, tzinfo=timezone.utc),
    )

    assert jobs[0].user.user_id == "user-1"
    assert "sj.next_run_at <= %(now)s" in service.last_query
    assert "FOR UPDATE SKIP LOCKED" in service.last_query
    assert service.last_params["worker_id"] == "worker-1"
    assert service.last_params["batch_size"] == 10


def test_get_status_reads_one_user_schedule_state():
    service = QueryCaptureScheduledJobs()

    status = service.get_status("user-1")

    assert status is not None
    assert "FROM scheduled_user_jobs" in service.last_query
    assert "WHERE athlete_id = %(user_id)s" in service.last_query
    assert service.last_params == {"user_id": "user-1"}
