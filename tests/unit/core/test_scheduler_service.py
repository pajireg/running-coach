"""Scheduler service tests."""

from __future__ import annotations

import schedule

from running_coach.core.scheduler import SchedulerService


def setup_function():
    schedule.clear()


def teardown_function():
    schedule.clear()


def test_scheduler_registers_daily_jobs_by_default():
    service = SchedulerService(
        lambda: None,
        schedule_times=["05:00", "17:00"],
        run_mode="auto",
        include_strength=False,
    )

    service._register_jobs()

    assert len(schedule.jobs) == 2


def test_scheduler_supports_minute_polling_mode():
    service = SchedulerService(
        lambda: None,
        schedule_times=["05:00", "17:00"],
        run_mode="auto",
        include_strength=False,
        poll_interval_minutes=1,
    )

    service._register_jobs()

    assert len(schedule.jobs) == 1
    assert schedule.jobs[0].interval == 1
    assert schedule.jobs[0].unit == "minutes"
