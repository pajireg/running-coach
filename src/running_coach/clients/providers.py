"""Provider capability protocols used by orchestration code."""

from __future__ import annotations

from datetime import date
from typing import Any, Protocol

from ..models.metrics import AdvancedMetrics
from ..models.training import Workout


class WorkoutDeliveryProvider(Protocol):
    """Capability for creating and scheduling planned workouts."""

    def create_workout(self, workout: Workout) -> str | None:
        """Create a provider-native workout and return its external id."""
        ...

    def schedule_workout(self, workout_id: str, target_date: date) -> Any:
        """Schedule a provider-native workout for a specific date."""
        ...


class TrainingDataProvider(Protocol):
    """Capability for collecting training, health, and schedule history."""

    workout_manager: WorkoutDeliveryProvider | None

    def login(self) -> None:
        """Authenticate the provider session before data or delivery calls."""
        ...

    def get_advanced_metrics(self, target_date: date | None = None) -> AdvancedMetrics:
        """Return normalized daily metrics for coaching."""
        ...

    def get_recent_activity_history(
        self,
        days: int = 42,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return recent activity history in the current normalized raw shape."""
        ...

    def get_recent_scheduled_workout_history(
        self,
        target_date: date | None = None,
        days: int = 84,
    ) -> list[dict[str, Any]]:
        """Return recent provider scheduled workout history."""
        ...

    def cleanup_existing_workouts(self, workout_ids: list[str] | None = None) -> int:
        """Delete or detach previously generated provider workouts."""
        ...
