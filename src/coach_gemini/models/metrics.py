"""통합 메트릭 모델"""
from pydantic import BaseModel
from datetime import date as DateType
from .health import HealthMetrics
from .performance import PerformanceMetrics
from .context import ActivityContext


class AdvancedMetrics(BaseModel):
    """통합 건강 및 퍼포먼스 지표"""
    date: DateType
    health: HealthMetrics
    performance: PerformanceMetrics
    context: ActivityContext

    def to_gemini_dict(self) -> dict:
        """Gemini API에 전달할 딕셔너리 형태로 변환"""
        return {
            "date": str(self.date),
            "health": self.health.to_dict(),
            "performance": self.performance.to_dict(),
            "context": self.context.to_dict()
        }

    def to_dict(self) -> dict:
        """기존 코드 호환성을 위한 딕셔너리 변환"""
        return {
            "health": self.health.to_dict(),
            "performance": self.performance.to_dict(),
            "context": self.context.to_dict()
        }
