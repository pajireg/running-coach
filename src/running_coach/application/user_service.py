"""User-scoped application services."""

from __future__ import annotations

from dataclasses import dataclass

from ..config.settings import Settings
from ..models.llm_settings import UserLLMSettingsPatch
from ..models.user import (
    IntegrationStatus,
    RunSyncResponse,
    UserContext,
    UserCreateRequest,
    UserCreateResponse,
    UserPreferences,
    UserPreferencesPatch,
    UserProfile,
    UserRecord,
)
from ..storage import AdminSettingsService, UserService
from .coaching_service import CoachingApplicationService


@dataclass
class UserApplicationService:
    """Application service for user-facing API and runtime context."""

    user_service: UserService
    admin_settings: AdminSettingsService
    settings: Settings
    coaching_service: CoachingApplicationService

    def create_user(self, payload: UserCreateRequest) -> UserCreateResponse:
        record, api_key = self.user_service.create_user(payload)
        return UserCreateResponse(apiKey=api_key, user=self._profile_from_record(record))

    def authenticate_api_key(self, api_key: str) -> UserContext | None:
        record = self.user_service.authenticate_api_key(api_key)
        if record is None:
            return None
        return self._context_from_record(record)

    def get_user_profile(self, user_id: str) -> UserProfile:
        return self._profile_from_record(self.user_service.get_user_record(user_id))

    def update_user_preferences(self, user_id: str, patch: UserPreferencesPatch) -> UserProfile:
        self.user_service.update_user_preferences(user_id, patch)
        llm_patch = self._llm_patch_from_preferences(patch)
        if llm_patch.model_fields_set:
            self.admin_settings.update_user_llm_settings(user_id, llm_patch)
        return self.get_user_profile(user_id)

    def get_user_context(self, user_id: str) -> UserContext:
        return self._context_from_record(self.user_service.get_user_record(user_id))

    def ensure_local_runtime_user_context(self) -> UserContext:
        record = self.user_service.upsert_runtime_user(
            external_key=self.settings.garmin_email.lower(),
            garmin_email=self.settings.garmin_email,
            timezone="Asia/Seoul",
            locale="ko",
            schedule_times=self.settings.schedule_times,
            include_strength=self.settings.include_strength,
        )
        return self._context_from_record(record)

    def run_user_sync(self, user_id: str, run_mode: str = "auto") -> RunSyncResponse:
        context = self.get_user_context(user_id)
        return self.coaching_service.run_for_user_context(context, run_mode=run_mode)

    def _profile_from_record(self, record: UserRecord) -> UserProfile:
        llm_settings = self.admin_settings.get_user_llm_settings(record.user_id).effective
        return UserProfile(
            userId=record.user_id,
            externalKey=record.external_key,
            displayName=record.display_name,
            garminEmail=record.garmin_email,
            preferences=UserPreferences(
                timezone=record.timezone,
                locale=record.locale or "ko",
                scheduleTimes=record.schedule_times or self.settings.schedule_times,
                includeStrength=(
                    record.include_strength
                    if record.include_strength is not None
                    else self.settings.include_strength
                ),
            ),
            llmSettings=llm_settings,
            integrationStatus=IntegrationStatus(
                garmin=self._garmin_status(record),
                googleCalendar=self._google_calendar_status(),
            ),
        )

    def _context_from_record(self, record: UserRecord) -> UserContext:
        llm_settings = self.admin_settings.get_user_llm_settings(record.user_id).effective
        return UserContext(
            user_id=record.user_id,
            external_key=record.external_key,
            display_name=record.display_name,
            garmin_email=record.garmin_email,
            timezone=record.timezone,
            locale=record.locale or "ko",
            schedule_times=record.schedule_times or self.settings.schedule_times,
            include_strength=(
                record.include_strength
                if record.include_strength is not None
                else self.settings.include_strength
            ),
            llm_settings=llm_settings,
        )

    def _garmin_status(self, record: UserRecord) -> str:
        if record.garmin_email:
            if record.garmin_email == self.settings.garmin_email:
                return "env_compat"
            return "configured"
        return "not_configured"

    def _google_calendar_status(self) -> str:
        return "env_compat"

    def _llm_patch_from_preferences(self, patch: UserPreferencesPatch) -> UserLLMSettingsPatch:
        payload = {}
        if "planner_mode" in patch.model_fields_set:
            payload["plannerMode"] = patch.planner_mode
        if "llm_provider" in patch.model_fields_set:
            payload["llmProvider"] = patch.llm_provider
        if "llm_model" in patch.model_fields_set:
            payload["llmModel"] = patch.llm_model
        return UserLLMSettingsPatch.model_validate(payload)
