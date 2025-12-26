"""퍼포먼스 지표 모델"""
from pydantic import BaseModel
from typing import Optional, List


class LactateThreshold(BaseModel):
    """젖산 역치"""
    pace: str  # "4:30/km"
    heart_rate: int


class PersonalRecord(BaseModel):
    """개인 기록"""
    type: str  # "5K", "10K", "HALF_MARATHON" 등
    time_seconds: float
    formatted_time: str  # "45m 30s"

    @property
    def display(self) -> str:
        """표시용 포맷"""
        return f"{self.type}: {self.formatted_time}"


class TrainingLoad(BaseModel):
    """훈련 부하"""
    status: str = "N/A"
    balance_phrase: str = "N/A"
    acwr: Optional[float] = None
    acute_load: Optional[float] = None
    chronic_load: Optional[float] = None

    @property
    def formatted_info(self) -> str:
        """포맷된 훈련 정보"""
        return (
            f"상태: {self.status}, 부하 밸런스: {self.balance_phrase}, "
            f"ACWR: {self.acwr}, 급성 부하: {self.acute_load}"
        )


class PerformanceMetrics(BaseModel):
    """퍼포먼스 지표"""
    personal_records: List[PersonalRecord] = []
    training_load: TrainingLoad = TrainingLoad()
    vo2_max: Optional[float] = None
    lactate_threshold: Optional[LactateThreshold] = None
    max_heart_rate: Optional[int] = None

    @property
    def training_info_for_gemini(self) -> str:
        """Gemini 프롬프트용 훈련 정보"""
        return self.training_load.formatted_info

    @property
    def pr_list_for_gemini(self) -> List[str]:
        """Gemini 프롬프트용 개인 기록 목록"""
        return [pr.display for pr in self.personal_records]

    def to_dict(self) -> dict:
        """딕셔너리로 변환 (기존 코드 호환성)"""
        return {
            "personalRecords": self.pr_list_for_gemini,
            "trainingStatus": self.training_load.status,
            "trainingDetails": self.training_load.formatted_info,
            "vo2Max": str(self.vo2_max) if self.vo2_max else "N/A",
            "lactateThreshold": {
                "pace": self.lactate_threshold.pace,
                "heartRate": self.lactate_threshold.heart_rate
            } if self.lactate_threshold else None,
            "maxHeartRate": self.max_heart_rate
        }
