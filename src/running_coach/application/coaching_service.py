"""User-scoped coaching application services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..config.settings import Settings
from ..core.container import ServiceContainer
from ..core.orchestrator import TrainingOrchestrator
from ..models.feedback import SubjectiveFeedback
from ..models.user import RunSyncResponse, UserContext


@dataclass
class CoachingApplicationService:
    """User-scoped application entrypoints for coaching workflows."""

    settings: Settings

    def run_for_user_context(
        self,
        user_context: UserContext,
        run_mode: str = "auto",
    ) -> RunSyncResponse:
        if not user_context.garmin_email:
            raise ValueError("Garmin integration is not configured for this user")
        if user_context.garmin_email != self.settings.garmin_email:
            raise ValueError(
                "Garmin credentials are not available for this user in this deployment"
            )

        container = ServiceContainer.create_for_user(
            settings=self.settings,
            user_context=user_context,
        )
        orchestrator = TrainingOrchestrator(container)
        result = orchestrator.run_once(run_mode=run_mode, user_context=user_context)
        return RunSyncResponse(
            status="completed" if result else "failed",
            mode=run_mode,
        )

    def record_feedback(self, user_context: UserContext, feedback: SubjectiveFeedback) -> None:
        history_service = self._history_service(user_context)
        history_service.record_subjective_feedback(feedback)

    def update_availability(
        self,
        user_context: UserContext,
        *,
        weekday: int,
        is_available: bool,
        max_duration_minutes: int | None,
        preferred_session_type: str | None,
    ) -> None:
        history_service = self._history_service(user_context)
        history_service.upsert_availability_rule(
            weekday=weekday,
            is_available=is_available,
            max_duration_minutes=max_duration_minutes,
            preferred_session_type=preferred_session_type,
        )

    def upsert_race_goal(
        self,
        user_context: UserContext,
        *,
        goal_name: str,
        race_date: date | None,
        distance: str | None,
        goal_time: str | None,
        target_pace: str | None,
        priority: int,
    ) -> None:
        history_service = self._history_service(user_context)
        history_service.upsert_race_goal(
            goal_name=goal_name,
            race_date=race_date,
            distance=distance,
            goal_time=goal_time,
            target_pace=target_pace,
            priority=priority,
        )

    def upsert_training_block(
        self,
        user_context: UserContext,
        *,
        phase: str,
        starts_on: date,
        ends_on: date,
        focus: str | None,
        weekly_volume_target_km: float | None,
    ) -> None:
        history_service = self._history_service(user_context)
        history_service.upsert_training_block(
            phase=phase,
            starts_on=starts_on,
            ends_on=ends_on,
            focus=focus,
            weekly_volume_target_km=weekly_volume_target_km,
        )

    def upsert_injury_status(
        self,
        user_context: UserContext,
        *,
        status_date: date,
        injury_area: str,
        severity: int,
        notes: str | None,
        is_active: bool,
    ) -> None:
        history_service = self._history_service(user_context)
        history_service.upsert_injury_status(
            status_date=status_date,
            injury_area=injury_area,
            severity=severity,
            notes=notes,
            is_active=is_active,
        )

    def _history_service(self, user_context: UserContext):
        container = ServiceContainer.create_for_user(
            settings=self.settings,
            user_context=user_context,
        )
        container.history_service.db.ping()
        container.history_service.ensure_athlete(
            garmin_email=user_context.garmin_email or self.settings.garmin_email,
            max_heart_rate=self.settings.max_heart_rate,
        )
        return container.history_service
