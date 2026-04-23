"""User-facing identity and preference models."""

from __future__ import annotations

from typing import Any

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
    include_strength: bool = Field(alias="includeStrength")

    model_config = ConfigDict(populate_by_name=True)


class IntegrationStatus(BaseModel):
    """High-level integration state."""

    garmin: str
    google_calendar: str = Field(alias="googleCalendar")

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
            include_strength=row.get("include_strength"),
            planner_mode=row.get("planner_mode"),
            llm_provider=row.get("llm_provider"),
            llm_model=row.get("llm_model"),
        )
