"""User-scoped coaching application services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from ..config.settings import Settings
from ..core.orchestrator import TrainingOrchestrator
from ..models.feedback import SubjectiveFeedback
from ..models.user import RunSyncResponse, UserContext
from ..storage import UserCoachingStateService


@dataclass
class CoachingApplicationService:
    """User-scoped application entrypoints for coaching workflows."""

    settings: Settings
    user_state_service: UserCoachingStateService
    runtime_factory: Any | None = None

    def run_for_user_context(
        self,
        user_context: UserContext,
        run_mode: str = "auto",
    ) -> RunSyncResponse:
        if self.runtime_factory is None:
            raise ValueError("User runtime factory is not configured")

        container = self.runtime_factory.create_container(user_context)
        orchestrator = TrainingOrchestrator(container)
        result = orchestrator.run_once(run_mode=run_mode, user_context=user_context)
        return RunSyncResponse(
            status="completed" if result else "failed",
            mode=run_mode,
        )

    def record_feedback(self, user_context: UserContext, feedback: SubjectiveFeedback) -> None:
        self._ensure_user_profile(user_context)
        self.user_state_service.record_subjective_feedback(user_context.user_id, feedback)

    def update_availability(
        self,
        user_context: UserContext,
        *,
        weekday: int,
        is_available: bool,
        max_duration_minutes: int | None,
        preferred_session_type: str | None,
    ) -> None:
        self._ensure_user_profile(user_context)
        self.user_state_service.upsert_availability_rule(
            user_context.user_id,
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
        self._ensure_user_profile(user_context)
        self.user_state_service.upsert_race_goal(
            user_context.user_id,
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
        self._ensure_user_profile(user_context)
        self.user_state_service.upsert_training_block(
            user_context.user_id,
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
        self._ensure_user_profile(user_context)
        self.user_state_service.upsert_injury_status(
            user_context.user_id,
            status_date=status_date,
            injury_area=injury_area,
            severity=severity,
            notes=notes,
            is_active=is_active,
        )

    def _ensure_user_profile(self, user_context: UserContext) -> None:
        self.user_state_service.db.ping()
        self.user_state_service.ensure_user_profile(
            user_id=user_context.user_id,
            garmin_email=user_context.garmin_email or self.settings.garmin_email,
            timezone=user_context.timezone,
            max_heart_rate=self.settings.max_heart_rate,
        )
