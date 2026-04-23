"""Write-side coaching history facade."""

from __future__ import annotations

from datetime import date
from typing import Any

from ..models.metrics import AdvancedMetrics
from ..models.training import TrainingPlan
from .history_service import CoachingHistoryService


class HistoryWriteService:
    """Write-oriented facade over coaching history persistence."""

    def __init__(self, history_service: CoachingHistoryService):
        self.history_service = history_service
        self.db = history_service.db

    def ensure_athlete(self, *, garmin_email: str, max_heart_rate: int | None) -> None:
        self.history_service.ensure_athlete(
            garmin_email=garmin_email,
            max_heart_rate=max_heart_rate,
        )

    def record_daily_metrics(self, metrics: AdvancedMetrics) -> None:
        self.history_service.record_daily_metrics(metrics)

    def record_training_plan(self, plan: TrainingPlan) -> None:
        self.history_service.record_training_plan(plan)

    def record_coach_decision(
        self,
        *,
        decision_date: date,
        summary: str,
        metrics: AdvancedMetrics,
        plan: TrainingPlan,
        training_background: Any,
    ) -> None:
        self.history_service.record_coach_decision(
            decision_date=decision_date,
            summary=summary,
            metrics=metrics,
            plan=plan,
            training_background=training_background,
        )

    def record_activities(self, activities: list[dict[str, Any]]) -> None:
        self.history_service.record_activities(activities)
