"""의존성 주입 컨테이너"""

from dataclasses import dataclass

from ..clients.garmin import GarminClient
from ..clients.gemini import GeminiClient
from ..clients.google_calendar import GoogleCalendarClient
from ..coaching.context import CoachingContextBuilder
from ..coaching.safety import DEFAULT_SAFETY_RULES, SafetyValidator
from ..config.settings import Settings
from ..storage import CoachingHistoryService, DatabaseClient


@dataclass
class ServiceContainer:
    """의존성 주입 컨테이너"""

    settings: Settings
    garmin_client: GarminClient
    gemini_client: GeminiClient
    calendar_client: GoogleCalendarClient
    history_service: CoachingHistoryService
    safety_validator: SafetyValidator
    context_builder: CoachingContextBuilder

    @classmethod
    def create(cls, settings: Settings) -> "ServiceContainer":
        """컨테이너 생성 및 의존성 주입"""
        history_service = CoachingHistoryService(
            db=DatabaseClient(settings.database_url),
            athlete_key=settings.garmin_email.lower(),
        )
        context_builder = CoachingContextBuilder(history_service=history_service)
        safety_validator = SafetyValidator(rules=list(DEFAULT_SAFETY_RULES))
        gemini_client = GeminiClient(
            api_key=settings.gemini_api_key,
            mode=settings.coach_planner_mode,
            context_builder=context_builder,
            safety_validator=safety_validator,
        )
        return cls(
            settings=settings,
            garmin_client=GarminClient(
                email=settings.garmin_email,
                password=settings.garmin_password,
                settings=settings,
            ),
            gemini_client=gemini_client,
            calendar_client=GoogleCalendarClient(),
            history_service=history_service,
            safety_validator=safety_validator,
            context_builder=context_builder,
        )
