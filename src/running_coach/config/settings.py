"""설정 관리"""

from datetime import date
from typing import Literal, Optional, cast

from pydantic_settings import BaseSettings, SettingsConfigDict

from ..models.config import RaceConfig
from ..models.llm_settings import LLMProvider, LLMSettings
from .constants import (
    DEFAULT_DB_NAME,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_PROVIDER,
    DEFAULT_SCHEDULE_HOUR,
    DEFAULT_SCHEDULE_TIMES,
    DEFAULT_SERVICE_RUN_MODE,
)


class Settings(BaseSettings):
    """환경변수 기반 설정 (기존 .env 파일 완전 호환)"""

    # Garmin 설정 (필수)
    garmin_email: str
    garmin_password: str

    # Gemini 설정 (필수)
    gemini_api_key: str

    # 관리자 API 설정
    admin_api_key: Optional[str] = None

    # 선택적 설정
    max_heart_rate: Optional[int] = None
    race_date: Optional[str] = None
    race_distance: Optional[str] = None
    race_goal_time: Optional[str] = None
    race_target_pace: Optional[str] = None
    database_url: str = f"postgresql://coach:coach@localhost:5432/{DEFAULT_DB_NAME}"
    persist_history: bool = True

    # 런타임 설정 (환경변수 아님)
    include_strength: bool = False
    service_mode: bool = False
    schedule_hour: int = DEFAULT_SCHEDULE_HOUR
    schedule_times: str = DEFAULT_SCHEDULE_TIMES
    service_run_mode: str = DEFAULT_SERVICE_RUN_MODE

    # Planner mode: 'legacy'(기존 skeleton) | 'llm_driven'(새 LLM 주도)
    coach_planner_mode: Literal["legacy", "llm_driven"] = "legacy"

    # 배포 기본 LLM 설정. DB admin/system settings 값이 우선한다.
    llm_provider: LLMProvider = cast(LLMProvider, DEFAULT_LLM_PROVIDER)
    llm_model: str = DEFAULT_LLM_MODEL

    # 후속 provider client 연결용 서비스 비밀값
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # 추가 환경변수 무시
    )

    @property
    def race(self) -> RaceConfig:
        """RaceConfig 객체로 변환"""
        # race_date 문자열을 DateType으로 변환
        date_obj = None
        if self.race_date:
            try:
                date_obj = date.fromisoformat(self.race_date)
            except ValueError:
                pass

        return RaceConfig(
            date=date_obj,
            distance=self.race_distance,
            goal_time=self.race_goal_time,
            target_pace=self.race_target_pace,
        )

    def validate_required(self) -> None:
        """필수 환경변수 검증"""
        missing = []
        if not self.garmin_email:
            missing.append("GARMIN_EMAIL")
        if not self.garmin_password:
            missing.append("GARMIN_PASSWORD")
        if not self.gemini_api_key:
            missing.append("GEMINI_API_KEY")

        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    def parsed_schedule_times(self) -> list[str]:
        """서비스 모드 실행 시각 목록을 HH:MM 형식으로 반환."""
        raw_times = [item.strip() for item in self.schedule_times.split(",") if item.strip()]
        if not raw_times:
            raw_times = [f"{self.schedule_hour:02d}:00"]

        normalized: list[str] = []
        for raw_time in raw_times:
            if ":" in raw_time:
                hour_text, minute_text = raw_time.split(":", 1)
            else:
                hour_text, minute_text = raw_time, "00"
            hour = int(hour_text)
            minute = int(minute_text)
            if not 0 <= hour <= 23 or not 0 <= minute <= 59:
                raise ValueError(f"Invalid schedule time: {raw_time}")
            normalized.append(f"{hour:02d}:{minute:02d}")
        return normalized

    def deployment_llm_settings(self) -> LLMSettings:
        """환경변수 기반 LLM fallback 설정."""
        return LLMSettings(
            planner_mode=self.coach_planner_mode,
            llm_provider=self.llm_provider,
            llm_model=self.llm_model,
        )


def get_settings() -> Settings:
    """설정 인스턴스 생성 및 검증"""
    settings = Settings()  # type: ignore[call-arg]
    settings.validate_required()
    return settings
