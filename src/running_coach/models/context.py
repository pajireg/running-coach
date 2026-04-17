"""활동 컨텍스트 모델"""

from __future__ import annotations

import datetime as dt
from typing import List, Optional

from pydantic import BaseModel, Field


class Activity(BaseModel):
    """활동 기록"""

    date: Optional[dt.date] = None
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
        if self.distance is not None:
            parts.append(f"{self.distance:.2f}km")
        if self.duration is not None:
            minutes = int(self.duration / 60)
            parts.append(f"{minutes}분")
        return " - ".join(parts) if parts else "활동 없음"


class ScheduleItem(BaseModel):
    """일정 항목"""

    date: dt.date
    title: str
    type: str  # "workout", "activity"
    details: str = ""

    @property
    def display(self) -> str:
        """표시용 포맷"""
        details = f" {self.details}" if self.details else ""
        return f"{self.date.isoformat()}: {self.title} ({self.type}){details}"


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

    yesterday_actual: List[Activity] = Field(default_factory=list)
    yesterday_planned: List[ScheduleItem] = Field(default_factory=list)
    current_schedule: List[ScheduleItem] = Field(default_factory=list)  # 최근 30일
    yearly_trend: List[MonthlyStats] = Field(default_factory=list)
    recent_7d_run_distance_km: float = 0.0
    recent_30d_run_distance_km: float = 0.0
    recent_30d_run_count: int = 0
    recent_7d_non_running_duration_minutes: int = 0
    recent_7d_non_running_sessions: int = 0
    recent_7d_non_running_types: List[str] = Field(default_factory=list)

    def to_dict(self) -> dict:
        """딕셔너리로 변환 (기존 코드 호환성)"""
        return {
            "yesterday_actual": [act.display for act in self.yesterday_actual],
            "yesterday_planned": [item.display for item in self.yesterday_planned],
            "current_schedule": [item.display for item in self.current_schedule],
            "yearly_trend": [stat.display for stat in self.yearly_trend],
            "recent7dRunDistanceKm": round(self.recent_7d_run_distance_km, 2),
            "recent30dRunDistanceKm": round(self.recent_30d_run_distance_km, 2),
            "recent30dRunCount": self.recent_30d_run_count,
            "recent7dNonRunningDurationMinutes": self.recent_7d_non_running_duration_minutes,
            "recent7dNonRunningSessions": self.recent_7d_non_running_sessions,
            "recent7dNonRunningTypes": self.recent_7d_non_running_types,
        }
