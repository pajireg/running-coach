"""활동 컨텍스트 모델"""
from pydantic import BaseModel
from typing import List, Optional
from datetime import date as DateType


class Activity(BaseModel):
    """활동 기록"""
    name: Optional[str] = None
    type: Optional[str] = None
    distance: Optional[float] = None
    duration: Optional[float] = None
    calories: Optional[int] = None

    @property
    def display(self) -> str:
        """표시용 포맷"""
        parts = []
        if self.name:
            parts.append(self.name)
        if self.distance:
            parts.append(f"{self.distance:.2f}km")
        if self.duration:
            minutes = int(self.duration / 60)
            parts.append(f"{minutes}분")
        return " - ".join(parts) if parts else "활동 없음"


class ScheduleItem(BaseModel):
    """일정 항목"""
    date: DateType
    title: str
    type: str  # "workout", "activity"
    details: str = ""

    @property
    def display(self) -> str:
        """표시용 포맷"""
        return f"{self.date.isoformat()}: {self.title} ({self.type})"


class MonthlyStats(BaseModel):
    """월간 통계"""
    year: int
    month: int
    distance_km: float
    activity_count: int

    @property
    def display(self) -> str:
        """표시용 포맷"""
        return f"{self.year}/{self.month:02d}: {self.distance_km:.1f}km ({self.activity_count}회)"


class ActivityContext(BaseModel):
    """활동 컨텍스트"""
    yesterday_actual: List[Activity] = []
    current_schedule: List[ScheduleItem] = []  # 최근 30일
    yearly_trend: List[MonthlyStats] = []

    def to_dict(self) -> dict:
        """딕셔너리로 변환 (기존 코드 호환성)"""
        return {
            "yesterday_actual": [act.display for act in self.yesterday_actual],
            "current_schedule": [item.display for item in self.current_schedule],
            "yearly_trend": [stat.display for stat in self.yearly_trend]
        }
