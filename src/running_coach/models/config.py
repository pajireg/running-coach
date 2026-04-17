"""설정 모델 정의"""

import re
from datetime import date
from typing import Optional

from pydantic import BaseModel, field_validator


class RaceConfig(BaseModel):
    """대회 목표 설정"""

    date: Optional[date] = None
    distance: Optional[str] = None  # "Full", "Half", "10K", "5K" 등
    goal_time: Optional[str] = None  # "3:59:59" or "59:59"
    target_pace: Optional[str] = None  # "5:40"

    @field_validator("goal_time", "target_pace")
    @classmethod
    def validate_time_format(cls, v: Optional[str]) -> Optional[str]:
        """시간 포맷 검증 (MM:SS 또는 H:MM:SS)"""
        if v and not re.match(r"^\d+:\d{2}(:\d{2})?$", v):
            raise ValueError(f"Invalid time format: {v}. Expected MM:SS or H:MM:SS")
        return v

    @property
    def has_goal(self) -> bool:
        """대회 목표가 설정되어 있는지"""
        return self.date is not None and self.distance is not None
