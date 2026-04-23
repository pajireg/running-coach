"""의존성 주입 컨테이너"""

from dataclasses import dataclass
from typing import Optional

from ..clients.garmin import GarminClient
from ..clients.gemini import GeminiClient
from ..clients.google_calendar import GoogleCalendarClient
from ..coaching.context import CoachingContextBuilder
from ..coaching.safety import DEFAULT_SAFETY_RULES, SafetyValidator
from ..config.settings import Settings
from ..models.user import UserContext
from ..storage import AdminSettingsService, CoachingHistoryService, DatabaseClient
from ..utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ServiceContainer:
    """의존성 주입 컨테이너"""

    settings: Settings
    user_context: Optional[UserContext]
    garmin_client: GarminClient
    gemini_client: GeminiClient
    calendar_client: GoogleCalendarClient
    history_service: CoachingHistoryService
    safety_validator: SafetyValidator
    context_builder: CoachingContextBuilder

    @classmethod
    def create(cls, settings: Settings) -> "ServiceContainer":
        """컨테이너 생성 및 의존성 주입"""
        return cls.create_for_user(
            settings=settings,
            user_context=None,
        )

    @classmethod
    def create_for_user(
        cls,
        settings: Settings,
        user_context: Optional[UserContext],
    ) -> "ServiceContainer":
        """배포 설정 + 사용자 컨텍스트로 컨테이너 생성."""
        db = DatabaseClient(settings.database_url)
        history_service = CoachingHistoryService(
            db=db,
            athlete_key=(
                user_context.external_key
                if user_context is not None
                else settings.garmin_email.lower()
            ),
            timezone=user_context.timezone if user_context is not None else "Asia/Seoul",
        )
        context_builder = CoachingContextBuilder(history_service=history_service)
        safety_validator = SafetyValidator(rules=list(DEFAULT_SAFETY_RULES))
        if user_context is not None:
            llm_settings = user_context.llm_settings
        else:
            llm_settings = settings.deployment_llm_settings()
            try:
                llm_settings = AdminSettingsService(
                    db=db,
                    deployment_defaults=llm_settings,
                ).get_global_llm_settings()
            except Exception as exc:
                logger.warning("관리자 LLM 설정 로드 실패; 배포 기본값 사용 (%s)", exc)

        planner_mode = llm_settings.planner_mode
        missing_provider_key = (
            llm_settings.llm_provider == "openai"
            and not settings.openai_api_key
            or llm_settings.llm_provider == "anthropic"
            and not settings.anthropic_api_key
        )
        if missing_provider_key and planner_mode == "llm_driven":
            logger.warning(
                "LLM provider=%s API key 누락; legacy planner 사용",
                llm_settings.llm_provider,
            )
            planner_mode = "legacy"

        gemini_client = GeminiClient(
            api_key=settings.gemini_api_key,
            mode=planner_mode,
            model=llm_settings.llm_model,
            llm_provider=llm_settings.llm_provider,
            openai_api_key=settings.openai_api_key,
            anthropic_api_key=settings.anthropic_api_key,
            context_builder=context_builder,
            safety_validator=safety_validator,
        )
        return cls(
            settings=settings,
            user_context=user_context,
            garmin_client=GarminClient(
                email=(
                    user_context.garmin_email
                    if user_context is not None and user_context.garmin_email
                    else settings.garmin_email
                ),
                password=settings.garmin_password,
                settings=settings,
            ),
            gemini_client=gemini_client,
            calendar_client=GoogleCalendarClient(),
            history_service=history_service,
            safety_validator=safety_validator,
            context_builder=context_builder,
        )
