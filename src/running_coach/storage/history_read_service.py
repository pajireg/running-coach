"""Read-side coaching history facade."""

from __future__ import annotations

from datetime import date
from typing import Any

from .history_service import CoachingHistoryService
from .plan_freshness_service import PlanFreshnessService


class HistoryReadService:
    """Read-oriented facade over coaching history persistence."""

    def __init__(
        self,
        history_service: CoachingHistoryService,
        plan_freshness_service: PlanFreshnessService | None = None,
    ):
        self.history_service = history_service
        self.plan_freshness_service = plan_freshness_service or PlanFreshnessService(
            db=history_service.db,
            athlete_key=history_service.athlete_key,
            timezone=history_service.timezone,
        )

    def summarize_training_background(self, as_of: date) -> dict[str, Any]:
        return self.history_service.summarize_training_background(as_of)

    def list_planned_external_workout_ids(
        self,
        *,
        start_date: date,
        end_date: date,
        delivery_provider: str = "garmin",
    ) -> list[str]:
        return self.plan_freshness_service.list_planned_external_workout_ids(
            start_date=start_date,
            end_date=end_date,
            delivery_provider=delivery_provider,
        )

    def summarize_plan_freshness(self, *, as_of: date) -> dict[str, Any]:
        return self.plan_freshness_service.summarize_plan_freshness(as_of=as_of)

    def fetch_future_plan(self, from_date: date, days: int = 6):
        return self.plan_freshness_service.fetch_future_plan(from_date, days=days)

    def list_recent_completed_activities(self, *, as_of: date, days: int = 2):
        return self.history_service.list_recent_completed_activities(as_of=as_of, days=days)
