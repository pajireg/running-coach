"""설정 관리"""
import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from datetime import date as DateType
from ..models.config import RaceConfig


class Settings(BaseSettings):
    """환경변수 기반 설정 (기존 .env 파일 완전 호환)"""

    # Garmin 설정 (필수)
    garmin_email: str
    garmin_password: str

    # Gemini 설정 (필수)
    gemini_api_key: str

    # 선택적 설정
    max_heart_rate: Optional[int] = None
    race_date: Optional[str] = None
    race_distance: Optional[str] = None
    race_goal_time: Optional[str] = None
    race_target_pace: Optional[str] = None

    # 런타임 설정 (환경변수 아님)
    include_strength: bool = False
    service_mode: bool = False
    schedule_hour: int = 6

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"  # 추가 환경변수 무시
    )

    @property
    def race(self) -> RaceConfig:
        """RaceConfig 객체로 변환"""
        # race_date 문자열을 DateType으로 변환
        date_obj = None
        if self.race_date:
            try:
                date_obj = DateType.fromisoformat(self.race_date)
            except ValueError:
                pass

        return RaceConfig(
            date=date_obj,
            distance=self.race_distance,
            goal_time=self.race_goal_time,
            target_pace=self.race_target_pace
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


def get_settings() -> Settings:
    """설정 인스턴스 생성 및 검증"""
    settings = Settings()
    settings.validate_required()
    return settings
