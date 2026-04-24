"""Client and provider capability boundaries."""

from .providers import TrainingDataProvider, WorkoutDeliveryProvider

__all__ = [
    "TrainingDataProvider",
    "WorkoutDeliveryProvider",
]
