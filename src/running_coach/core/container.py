"""의존성 주입 컨테이너"""

from dataclasses import dataclass

from ..clients.garmin import GarminClient
from ..clients.gemini import GeminiClient
from ..clients.google_calendar import GoogleCalendarClient
from ..coaching.context import CoachingContextBuilder
from ..coaching.safety import DEFAULT_SAFETY_RULES, SafetyValidator
from ..config.settings import Settings
from ..storage import AdminSettingsService, CoachingHistoryService, DatabaseClient
from ..utils.logger import get_logger

logger = get_logger(__name__)


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
        db = DatabaseClient(settings.database_url)
        history_service = CoachingHistoryService(
            db=db,
            athlete_key=settings.garmin_email.lower(),
        )
        context_builder = CoachingContextBuilder(history_service=history_service)
        safety_validator = SafetyValidator(rules=list(DEFAULT_SAFETY_RULES))
        llm_settings = settings.deployment_llm_settings()
        try:
            llm_settings = AdminSettingsService(
                db=db,
                deployment_defaults=llm_settings,
            ).get_global_llm_settings()
        except Exception as exc:
            logger.warning("관리자 LLM 설정 로드 실패; 배포 기본값 사용 (%s)", exc)

        planner_mode = llm_settings.planner_mode
        if llm_settings.llm_provider != "gemini" and planner_mode == "llm_driven":
            logger.warning(
                "LLM provider=%s 는 아직 런타임 planner에 연결되지 않음; legacy planner 사용",
                llm_settings.llm_provider,
            )
            planner_mode = "legacy"

        gemini_client = GeminiClient(
            api_key=settings.gemini_api_key,
            mode=planner_mode,
            model=llm_settings.llm_model,
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
