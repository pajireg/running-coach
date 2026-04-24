"""User-facing identity and preference models."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .llm_settings import LLMProvider, LLMSettings, PlannerMode


class UserCreateRequest(BaseModel):
    """Create a new product-facing user."""

    external_key: str | None = Field(default=None, alias="externalKey")
    display_name: str | None = Field(default=None, alias="displayName")
    garmin_email: str | None = Field(default=None, alias="garminEmail")
    timezone: str = "Asia/Seoul"
    locale: str = "ko"
    schedule_times: str = Field(default="05:00,17:00", alias="scheduleTimes")
    run_mode: Literal["plan", "auto"] = Field(default="auto", alias="runMode")
    include_strength: bool = Field(default=False, alias="includeStrength")

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    @field_validator("external_key", "display_name", "garmin_email")
    @classmethod
    def validate_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class UserPreferencesPatch(BaseModel):
    """Patch user-visible preferences."""

    display_name: str | None = Field(default=None, alias="displayName")
    garmin_email: str | None = Field(default=None, alias="garminEmail")
    timezone: str | None = None
    locale: str | None = None
    schedule_times: str | None = Field(default=None, alias="scheduleTimes")
    run_mode: Literal["plan", "auto"] | None = Field(default=None, alias="runMode")
    include_strength: bool | None = Field(default=None, alias="includeStrength")
    planner_mode: PlannerMode | None = Field(default=None, alias="plannerMode")
    llm_provider: LLMProvider | None = Field(default=None, alias="llmProvider")
    llm_model: str | None = Field(default=None, alias="llmModel")

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    @field_validator("display_name", "garmin_email", "timezone", "locale", "schedule_times")
    @classmethod
    def validate_patch_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("llm_model")
    @classmethod
    def validate_optional_model_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("llmModel must not be empty")
        return normalized


class UserPreferences(BaseModel):
    """Resolved user preference view."""

    timezone: str
    locale: str
    schedule_times: str = Field(alias="scheduleTimes")
    run_mode: str = Field(alias="runMode")
    include_strength: bool = Field(alias="includeStrength")

    model_config = ConfigDict(populate_by_name=True)


class IntegrationStatus(BaseModel):
    """High-level integration state."""

    garmin: str
    google_calendar: str = Field(alias="googleCalendar")

    model_config = ConfigDict(populate_by_name=True)


IntegrationProviderName = Literal[
    "garmin",
    "google_calendar",
    "healthkit",
    "health_connect",
    "google_fit",
]
IntegrationConnectionStatus = Literal[
    "active",
    "configured",
    "env_compat",
    "reauth_required",
    "disabled",
    "error",
    "not_configured",
    "coming_soon",
]


class IntegrationConnection(BaseModel):
    """App-facing provider connection summary without credential payloads."""

    provider: IntegrationProviderName
    display_name: str = Field(alias="displayName")
    status: IntegrationConnectionStatus
    connected: bool
    source: Literal["db", "env_compat", "profile", "none", "planned"]
    capabilities: list[str]
    last_error: str | None = Field(default=None, alias="lastError")

    model_config = ConfigDict(populate_by_name=True)


class UserIntegrationsResponse(BaseModel):
    """Current user's integration inventory."""

    integrations: list[IntegrationConnection]

    model_config = ConfigDict(populate_by_name=True)


class UserProfile(BaseModel):
    """User-facing profile payload."""

    user_id: str = Field(alias="userId")
    external_key: str = Field(alias="externalKey")
    display_name: str | None = Field(default=None, alias="displayName")
    garmin_email: str | None = Field(default=None, alias="garminEmail")
    preferences: UserPreferences
    llm_settings: LLMSettings = Field(alias="llmSettings")
    integration_status: IntegrationStatus = Field(alias="integrationStatus")

    model_config = ConfigDict(populate_by_name=True)


class UserCreateResponse(BaseModel):
    """One-time user creation response including raw API key."""

    api_key: str = Field(alias="apiKey")
    user: UserProfile

    model_config = ConfigDict(populate_by_name=True)


class UserScheduleStatus(BaseModel):
    """Read model for the user's background coaching schedule."""

    next_run_at: datetime | None = Field(default=None, alias="nextRunAt")
    last_run_at: datetime | None = Field(default=None, alias="lastRunAt")
    last_status: str | None = Field(default=None, alias="lastStatus")
    last_error: str | None = Field(default=None, alias="lastError")
    failure_count: int = Field(default=0, alias="failureCount")
    next_retry_at: datetime | None = Field(default=None, alias="nextRetryAt")
    disabled_at: datetime | None = Field(default=None, alias="disabledAt")
    lease_until: datetime | None = Field(default=None, alias="leaseUntil")

    model_config = ConfigDict(populate_by_name=True)


class DashboardPlannedWorkout(BaseModel):
    """Compact planned workout summary for app home screens."""

    date: date
    workout_name: str = Field(alias="workoutName")
    session_type: str | None = Field(default=None, alias="sessionType")
    workout_type: str | None = Field(default=None, alias="workoutType")
    planned_minutes: int | None = Field(default=None, alias="plannedMinutes")
    is_rest: bool = Field(alias="isRest")

    model_config = ConfigDict(populate_by_name=True)


class DashboardActivity(BaseModel):
    """Compact completed activity summary for app home screens."""

    provider: str | None = None
    provider_activity_id: str | None = Field(default=None, alias="providerActivityId")
    activity_date: date = Field(alias="activityDate")
    started_at: datetime | None = Field(default=None, alias="startedAt")
    title: str
    sport_type: str | None = Field(default=None, alias="sportType")
    distance_km: float | None = Field(default=None, alias="distanceKm")
    duration_seconds: int | None = Field(default=None, alias="durationSeconds")
    avg_pace: str | None = Field(default=None, alias="avgPace")
    avg_hr: int | None = Field(default=None, alias="avgHr")
    planned_workout_name: str | None = Field(default=None, alias="plannedWorkoutName")
    execution_status: str | None = Field(default=None, alias="executionStatus")
    execution_quality: str | None = Field(default=None, alias="executionQuality")
    target_match_score: float | None = Field(default=None, alias="targetMatchScore")

    model_config = ConfigDict(populate_by_name=True)


class UserDashboard(BaseModel):
    """App home dashboard contract."""

    user: UserProfile
    schedule: UserScheduleStatus
    current_plan: list[DashboardPlannedWorkout] = Field(alias="currentPlan")
    recent_activities: list[DashboardActivity] = Field(alias="recentActivities")

    model_config = ConfigDict(populate_by_name=True)


class RunSyncRequest(BaseModel):
    """Trigger a user-scoped sync run."""

    mode: str = "auto"

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, value: str) -> str:
        normalized = value.strip()
        if normalized not in {"plan", "auto"}:
            raise ValueError("mode must be 'plan' or 'auto'")
        return normalized


class RunSyncResponse(BaseModel):
    """Result payload for a user-triggered sync run."""

    status: str
    mode: str


class UserContext(BaseModel):
    """Resolved runtime context for a specific user."""

    user_id: str
    external_key: str
    display_name: str | None = None
    garmin_email: str | None = None
    timezone: str = "Asia/Seoul"
    locale: str = "ko"
    schedule_times: str = "05:00,17:00"
    run_mode: Literal["plan", "auto"] = "auto"
    include_strength: bool = False
    llm_settings: LLMSettings

    model_config = ConfigDict(populate_by_name=True)


class UserRecord(BaseModel):
    """Internal storage projection for a user row."""

    user_id: str
    external_key: str
    display_name: str | None = None
    garmin_email: str | None = None
    timezone: str = "Asia/Seoul"
    locale: str | None = None
    schedule_times: str | None = None
    run_mode: Literal["plan", "auto"] | None = None
    include_strength: bool | None = None
    planner_mode: PlannerMode | None = None
    llm_provider: LLMProvider | None = None
    llm_model: str | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "UserRecord":
        return cls(
            user_id=str(row["user_id"]),
            external_key=str(row["external_key"]),
            display_name=row.get("display_name"),
            garmin_email=row.get("garmin_email"),
            timezone=str(row.get("timezone") or "Asia/Seoul"),
            locale=row.get("locale"),
            schedule_times=row.get("schedule_times"),
            run_mode=row.get("run_mode"),
            include_strength=row.get("include_strength"),
            planner_mode=row.get("planner_mode"),
            llm_provider=row.get("llm_provider"),
            llm_model=row.get("llm_model"),
        )
