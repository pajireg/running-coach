"""건강 지표 모델"""
from pydantic import BaseModel
from typing import Optional


class SleepDetails(BaseModel):
    """수면 상세 정보"""
    score: Optional[int] = None
    quality: Optional[str] = None
    duration: str = "0분"
    deep: str = "0분"
    light: str = "0분"
    rem: str = "0분"
    awake: str = "0분"

    @property
    def formatted_info(self) -> str:
        """포맷된 수면 정보"""
        if not self.score:
            return "기록 없음"
        return (
            f"점수: {self.score} ({self.quality}), "
            f"총 수면: {self.duration} "
            f"(깊은: {self.deep}, 가벼운: {self.light}, REM: {self.rem}, 깨어남: {self.awake})"
        )


class HealthMetrics(BaseModel):
    """일일 건강 지표"""
    steps: Optional[int] = None
    sleep_score: Optional[int] = None
    sleep_details: Optional[SleepDetails] = None
    resting_hr: Optional[int] = None
    body_battery: Optional[int] = None
    hrv: Optional[int] = None

    @property
    def sleep_info_for_gemini(self) -> str:
        """Gemini 프롬프트용 수면 정보 텍스트"""
        if not self.sleep_details or not self.sleep_details.score:
            return "기록 없음"
        return self.sleep_details.formatted_info

    def to_dict(self) -> dict:
        """딕셔너리로 변환 (기존 코드 호환성)"""
        return {
            "steps": self.steps,
            "sleepScore": self.sleep_score,
            "sleepDetails": self.sleep_details.model_dump() if self.sleep_details else None,
            "restingHR": self.resting_hr,
            "bodyBattery": self.body_battery,
            "hrv": self.hrv
        }
