"""User-scoped application services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..config.settings import Settings
from ..models.feedback import SubjectiveFeedback
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
from ..storage import (
    AdminSettingsService,
    ClaimedUserJob,
    IntegrationCredentialService,
    ScheduledUserJobService,
    UserService,
)
from .coaching_service import CoachingApplicationService


@dataclass
class UserApplicationService:
    """Application service for user-facing API and runtime context."""

    user_service: UserService
    admin_settings: AdminSettingsService
    settings: Settings
    coaching_service: CoachingApplicationService
    integration_credentials: IntegrationCredentialService | None = None
    scheduled_jobs: ScheduledUserJobService | None = None

    def create_user(self, payload: UserCreateRequest) -> UserCreateResponse:
        record, api_key = self.user_service.create_user(payload)
        self._upsert_schedule(record)
        return UserCreateResponse(apiKey=api_key, user=self._profile_from_record(record))

    def authenticate_api_key(self, api_key: str) -> UserContext | None:
        record = self.user_service.authenticate_api_key(api_key)
        if record is None:
            return None
        return self._context_from_record(record)

    def get_user_profile(self, user_id: str) -> UserProfile:
        return self._profile_from_record(self.user_service.get_user_record(user_id))

    def update_user_preferences(self, user_id: str, patch: UserPreferencesPatch) -> UserProfile:
        record = self.user_service.update_user_preferences(user_id, patch)
        llm_patch = self._llm_patch_from_preferences(patch)
        if llm_patch.model_fields_set:
            self.admin_settings.update_user_llm_settings(user_id, llm_patch)
        if {"timezone", "schedule_times", "run_mode"} & patch.model_fields_set:
            self._upsert_schedule(record)
        return self.get_user_profile(user_id)

    def get_user_context(self, user_id: str) -> UserContext:
        return self._context_from_record(self.user_service.get_user_record(user_id))

    def list_runnable_user_contexts(self) -> list[UserContext]:
        records = self.user_service.list_runnable_users(
            deployment_garmin_email=self.settings.garmin_email,
        )
        return [self._context_from_record(record) for record in records]

    def claim_due_user_contexts(
        self,
        *,
        worker_id: str,
        batch_size: int,
    ) -> list[UserContext]:
        if self.scheduled_jobs is None:
            return self.list_runnable_user_contexts()
        claimed_jobs = self.scheduled_jobs.claim_due_users(
            deployment_garmin_email=self.settings.garmin_email,
            worker_id=worker_id,
            batch_size=batch_size,
        )
        return [self._context_from_claimed_job(job) for job in claimed_jobs]

    def ensure_local_runtime_user_context(self) -> UserContext:
        record = self.user_service.upsert_runtime_user(
            external_key=self.settings.garmin_email.lower(),
            garmin_email=self.settings.garmin_email,
            timezone="Asia/Seoul",
            locale="ko",
            schedule_times=self.settings.schedule_times,
            run_mode=self.settings.service_run_mode,
            include_strength=self.settings.include_strength,
        )
        self._upsert_schedule(record)
        return self._context_from_record(record)

    def run_user_sync(self, user_id: str, run_mode: str = "auto") -> RunSyncResponse:
        context = self.get_user_context(user_id)
        return self.coaching_service.run_for_user_context(context, run_mode=run_mode)

    def record_feedback(self, user_id: str, feedback: SubjectiveFeedback) -> None:
        self.coaching_service.record_feedback(self.get_user_context(user_id), feedback)

    def update_availability(
        self,
        user_id: str,
        *,
        weekday: int,
        is_available: bool,
        max_duration_minutes: int | None,
        preferred_session_type: str | None,
    ) -> None:
        self.coaching_service.update_availability(
            self.get_user_context(user_id),
            weekday=weekday,
            is_available=is_available,
            max_duration_minutes=max_duration_minutes,
            preferred_session_type=preferred_session_type,
        )

    def upsert_race_goal(
        self,
        user_id: str,
        *,
        goal_name: str,
        race_date: date | None,
        distance: str | None,
        goal_time: str | None,
        target_pace: str | None,
        priority: int,
        is_active: bool = True,
    ) -> None:
        self.coaching_service.upsert_race_goal(
            self.get_user_context(user_id),
            goal_name=goal_name,
            race_date=race_date,
            distance=distance,
            goal_time=goal_time,
            target_pace=target_pace,
            priority=priority,
            is_active=is_active,
        )

    def upsert_training_block(
        self,
        user_id: str,
        *,
        phase: str,
        starts_on: date,
        ends_on: date,
        focus: str | None,
        weekly_volume_target_km: float | None,
    ) -> None:
        self.coaching_service.upsert_training_block(
            self.get_user_context(user_id),
            phase=phase,
            starts_on=starts_on,
            ends_on=ends_on,
            focus=focus,
            weekly_volume_target_km=weekly_volume_target_km,
        )

    def upsert_injury_status(
        self,
        user_id: str,
        *,
        status_date: date,
        injury_area: str,
        severity: int,
        notes: str | None,
        is_active: bool,
    ) -> None:
        self.coaching_service.upsert_injury_status(
            self.get_user_context(user_id),
            status_date=status_date,
            injury_area=injury_area,
            severity=severity,
            notes=notes,
            is_active=is_active,
        )

    def _profile_from_record(self, record: UserRecord) -> UserProfile:
        llm_settings = self.admin_settings.get_user_llm_settings(record.user_id).effective
        integration_statuses = self._integration_statuses(record.user_id)
        return UserProfile(
            userId=record.user_id,
            externalKey=record.external_key,
            displayName=record.display_name,
            garminEmail=record.garmin_email,
            preferences=UserPreferences(
                timezone=record.timezone,
                locale=record.locale or "ko",
                scheduleTimes=record.schedule_times or self.settings.schedule_times,
                runMode=record.run_mode or self.settings.service_run_mode,
                includeStrength=(
                    record.include_strength
                    if record.include_strength is not None
                    else self.settings.include_strength
                ),
            ),
            llmSettings=llm_settings,
            integrationStatus=IntegrationStatus(
                garmin=self._garmin_status(record, integration_statuses),
                googleCalendar=self._google_calendar_status(integration_statuses),
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
            run_mode=record.run_mode or self.settings.service_run_mode,
            include_strength=(
                record.include_strength
                if record.include_strength is not None
                else self.settings.include_strength
            ),
            llm_settings=llm_settings,
        )

    def _context_from_claimed_job(self, job: ClaimedUserJob) -> UserContext:
        return self._context_from_record(job.user)

    def complete_scheduled_run(
        self,
        context: UserContext,
        *,
        status: str,
        error: str | None,
    ) -> None:
        if self.scheduled_jobs is None:
            return
        if status == "completed":
            self.scheduled_jobs.complete_success(context)
        else:
            self.scheduled_jobs.complete_failure(
                context,
                error=error or status,
            )

    def _upsert_schedule(self, record: UserRecord) -> None:
        if self.scheduled_jobs is None:
            return
        self.scheduled_jobs.upsert_for_user(self._context_from_record(record))

    def _integration_statuses(self, user_id: str) -> dict[str, str]:
        if self.integration_credentials is None:
            return {}
        return dict(self.integration_credentials.get_statuses(user_id))

    def _garmin_status(self, record: UserRecord, statuses: dict[str, str]) -> str:
        if "garmin" in statuses:
            return statuses["garmin"]
        if record.garmin_email:
            if record.garmin_email == self.settings.garmin_email:
                return "env_compat"
            return "configured"
        return "not_configured"

    def _google_calendar_status(self, statuses: dict[str, str]) -> str:
        if "google_calendar" in statuses:
            return statuses["google_calendar"]
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
