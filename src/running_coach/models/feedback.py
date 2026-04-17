"""주관 피드백 모델."""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class SubjectiveFeedback(BaseModel):
    """선수의 일일 주관 피드백."""

    feedback_date: date = Field(alias="feedbackDate")
    fatigue_score: Optional[int] = Field(default=None, alias="fatigueScore")
    soreness_score: Optional[int] = Field(default=None, alias="sorenessScore")
    stress_score: Optional[int] = Field(default=None, alias="stressScore")
    motivation_score: Optional[int] = Field(default=None, alias="motivationScore")
    sleep_quality_score: Optional[int] = Field(default=None, alias="sleepQualityScore")
    pain_notes: Optional[str] = Field(default=None, alias="painNotes")
    notes: Optional[str] = None

    @field_validator(
        "fatigue_score",
        "soreness_score",
        "stress_score",
        "motivation_score",
        "sleep_quality_score",
    )
    @classmethod
    def validate_score(cls, value: Optional[int]) -> Optional[int]:
        """1~10 범위 점수 검증."""
        if value is None:
            return None
        if not 1 <= value <= 10:
            raise ValueError("Feedback scores must be between 1 and 10")
        return value
