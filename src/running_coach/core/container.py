"""의존성 주입 컨테이너"""

from dataclasses import dataclass

from ..clients.garmin import GarminClient
from ..clients.gemini import GeminiClient
from ..clients.google_calendar import GoogleCalendarClient
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

    @classmethod
    def create(cls, settings: Settings) -> "ServiceContainer":
        """컨테이너 생성 및 의존성 주입

        Args:
            settings: Settings 인스턴스

        Returns:
            ServiceContainer 인스턴스
        """
        return cls(
            settings=settings,
            garmin_client=GarminClient(
                email=settings.garmin_email, password=settings.garmin_password, settings=settings
            ),
            gemini_client=GeminiClient(api_key=settings.gemini_api_key),
            calendar_client=GoogleCalendarClient(),
            history_service=CoachingHistoryService(
                db=DatabaseClient(settings.database_url),
                athlete_key=settings.garmin_email.lower(),
            ),
        )
