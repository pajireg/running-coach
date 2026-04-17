"""훈련 계획 모델"""

import re
from datetime import date, timedelta
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class WorkoutStep(BaseModel):
    """워크아웃 단계"""

    type: Literal["Warmup", "Run", "Interval", "Recovery", "Cooldown", "Rest"]
    duration_value: int = Field(gt=0, alias="durationValue")  # 초 단위
    duration_unit: Literal["second"] = Field(default="second", alias="durationUnit")
    target_type: Literal["no_target", "speed"] = Field(default="no_target", alias="targetType")
    target_value: Optional[str] = Field(default="0:00", alias="targetValue")  # "MM:SS" 페이스 형식

    @field_validator("target_value", mode="before")
    @classmethod
    def normalize_target_value(cls, v):
        """None 값을 기본값으로 변환"""
        if v is None:
            return "0:00"
        if isinstance(v, str):
            return v.replace("/km", "").strip()
        return v

    @model_validator(mode="after")
    def validate_target(self) -> "WorkoutStep":
        """타겟 형식 검증"""
        if self.target_type == "speed":
            if not re.fullmatch(r"\d+:\d{2}", self.target_value or ""):
                raise ValueError("Speed targetValue must use MM:SS format")
        elif self.target_value in (None, ""):
            self.target_value = "0:00"
        return self

    model_config = ConfigDict(populate_by_name=True)


class Workout(BaseModel):
    """워크아웃 정보"""

    workout_name: str = Field(alias="workoutName")
    description: str = ""  # 한국어 설명
    sport_type: Literal["RUNNING"] = Field(default="RUNNING", alias="sportType")
    steps: List[WorkoutStep] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)

    @property
    def is_rest(self) -> bool:
        """휴식 워크아웃인지"""
        return "Rest" in self.workout_name or "rest" in self.workout_name.lower()

    @property
    def total_duration(self) -> int:
        """전체 소요 시간 (초)"""
        return sum(step.duration_value for step in self.steps)

    @property
    def total_duration_minutes(self) -> int:
        """전체 소요 시간 (분)"""
        return self.total_duration // 60

    @model_validator(mode="after")
    def validate_workout(self) -> "Workout":
        """워크아웃 구조 검증"""
        if self.is_rest:
            return self
        if not self.steps:
            raise ValueError("Non-rest workout must include at least one step")
        return self


class DailyPlan(BaseModel):
    """일일 계획"""

    date: date
    workout: Workout


class TrainingPlan(BaseModel):
    """7일 훈련 계획"""

    plan: List[DailyPlan] = Field(min_length=7, max_length=7)
    created_at: date = Field(default_factory=date.today)

    @property
    def start_date(self) -> date:
        """계획 시작일"""
        return self.plan[0].date if self.plan else date.today()

    @property
    def end_date(self) -> date:
        """계획 종료일"""
        return self.plan[-1].date if self.plan else date.today()

    @property
    def total_workouts(self) -> int:
        """총 워크아웃 수 (휴식 제외)"""
        return sum(1 for day in self.plan if not day.workout.is_rest)

    @model_validator(mode="after")
    def validate_schedule(self) -> "TrainingPlan":
        """7일 연속 일정 검증"""
        if not self.plan:
            return self

        expected_date = self.plan[0].date
        for day in self.plan:
            if day.date != expected_date:
                raise ValueError("Training plan dates must be 7 consecutive days")
            expected_date += timedelta(days=1)

        return self
