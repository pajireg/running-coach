"""User-facing coaching workflow models."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MutationResponse(BaseModel):
    """Generic mutation response payload."""

    status: str = "ok"


class AvailabilityRuleRequest(BaseModel):
    """User-facing availability update payload."""

    weekday: int
    is_available: bool = Field(default=True, alias="isAvailable")
    max_duration_minutes: int | None = Field(default=None, alias="maxDurationMinutes")
    preferred_session_type: str | None = Field(default=None, alias="preferredSessionType")

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    @field_validator("weekday")
    @classmethod
    def validate_weekday(cls, value: int) -> int:
        if not 0 <= value <= 6:
            raise ValueError("weekday must be between 0 and 6")
        return value


class RaceGoalRequest(BaseModel):
    """User-facing race-goal upsert payload."""

    goal_name: str = Field(alias="goalName")
    race_date: date | None = Field(default=None, alias="raceDate")
    distance: str | None = None
    goal_time: str | None = Field(default=None, alias="goalTime")
    target_pace: str | None = Field(default=None, alias="targetPace")
    priority: int = 1
    is_active: bool = Field(default=True, alias="isActive")

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)


class TrainingBlockRequest(BaseModel):
    """User-facing training-block upsert payload."""

    phase: str
    starts_on: date = Field(alias="startsOn")
    ends_on: date = Field(alias="endsOn")
    focus: str | None = None
    weekly_volume_target_km: float | None = Field(default=None, alias="weeklyVolumeTargetKm")

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)


class InjuryStatusRequest(BaseModel):
    """User-facing injury-status upsert payload."""

    status_date: date = Field(alias="statusDate")
    injury_area: str = Field(alias="injuryArea")
    severity: int
    notes: str | None = None
    is_active: bool = Field(default=True, alias="isActive")

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, value: int) -> int:
        if not 0 <= value <= 10:
            raise ValueError("severity must be between 0 and 10")
        return value
