"""Coach Gemini: AI-powered adaptive running coach using Garmin data and Google Gemini"""

__version__ = "2.0.0"

from .core.container import ServiceContainer
from .core.orchestrator import TrainingOrchestrator
from .core.scheduler import SchedulerService

__all__ = [
    "ServiceContainer",
    "TrainingOrchestrator",
    "SchedulerService",
    "__version__",
]
