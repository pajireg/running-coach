"""Sync-state facade for coaching history."""

from __future__ import annotations

from datetime import date
from typing import Any

from .history_service import CoachingHistoryService


class HistorySyncService:
    """Facade for synchronization and execution-tracking state."""

    def __init__(self, history_service: CoachingHistoryService):
        self.history_service = history_service

    def rebuild_recent_workout_executions(self, *, as_of: date) -> int:
        return self.history_service.rebuild_recent_workout_executions(as_of=as_of)

    def backfill_planned_workouts(self, scheduled_items: list[dict[str, Any]]) -> int:
        return self.history_service.backfill_planned_workouts(scheduled_items)

    def clear_garmin_sync_results(self, *, start_date: date, end_date: date) -> None:
        self.history_service.clear_garmin_sync_results(start_date=start_date, end_date=end_date)

    def record_garmin_sync_result(
        self,
        *,
        workout_date: date,
        garmin_workout_id: str | None,
        garmin_schedule_status: str,
    ) -> None:
        self.history_service.record_garmin_sync_result(
            workout_date=workout_date,
            garmin_workout_id=garmin_workout_id,
            garmin_schedule_status=garmin_schedule_status,
        )
