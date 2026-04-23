"""User application service tests."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from running_coach.application.coaching_service import CoachingApplicationService
from running_coach.application.user_service import UserApplicationService
from running_coach.models.feedback import SubjectiveFeedback
from running_coach.models.llm_settings import LLMSettings, UserLLMSettings
from running_coach.models.user import UserCreateRequest, UserPreferencesPatch, UserRecord
from running_coach.storage.user_service import UserService


class FakeUserService(UserService):
    def __init__(self):
        super().__init__(db=object())  # type: ignore[arg-type]
        self.record = UserRecord(
            user_id="user-1",
            external_key="runner-1",
            display_name="Runner One",
            garmin_email="runner@example.com",
            timezone="Asia/Seoul",
            locale="ko",
            schedule_times="05:00,17:00",
            include_strength=False,
        )

    def create_user(self, payload: UserCreateRequest):  # type: ignore[override]
        self.record.display_name = payload.display_name
        self.record.garmin_email = payload.garmin_email
        self.record.timezone = payload.timezone
        self.record.locale = payload.locale
        self.record.schedule_times = payload.schedule_times
        self.record.include_strength = payload.include_strength
        return self.record, "rcu_test"

    def get_user_record(self, user_id: str) -> UserRecord:  # type: ignore[override]
        assert user_id == "user-1"
        return self.record

    def update_user_preferences(self, user_id: str, patch: UserPreferencesPatch) -> UserRecord:  # type: ignore[override]
        assert user_id == "user-1"
        if "display_name" in patch.model_fields_set:
            self.record.display_name = patch.display_name
        if "locale" in patch.model_fields_set:
            self.record.locale = patch.locale
        if "schedule_times" in patch.model_fields_set:
            self.record.schedule_times = patch.schedule_times
        if "include_strength" in patch.model_fields_set:
            self.record.include_strength = patch.include_strength
        if "garmin_email" in patch.model_fields_set:
            self.record.garmin_email = patch.garmin_email
        return self.record

    def upsert_runtime_user(self, **kwargs) -> UserRecord:  # type: ignore[override]
        self.record.external_key = kwargs["external_key"]
        self.record.garmin_email = kwargs["garmin_email"]
        self.record.timezone = kwargs["timezone"]
        self.record.locale = kwargs["locale"]
        self.record.schedule_times = kwargs["schedule_times"]
        self.record.include_strength = kwargs["include_strength"]
        return self.record


class FakeAdminSettings:
    def __init__(self):
        self.global_settings = LLMSettings(
            planner_mode="legacy",
            llm_provider="gemini",
            llm_model="gemini-2.5-flash",
        )
        self.last_patch = None

    def get_user_llm_settings(self, user_id: str) -> UserLLMSettings:
        assert user_id == "user-1"
        return UserLLMSettings(
            user_id=user_id,
            effective=self.global_settings,
        )

    def update_user_llm_settings(self, user_id: str, patch):
        assert user_id == "user-1"
        self.last_patch = patch
        self.global_settings = LLMSettings(
            planner_mode=patch.planner_mode or self.global_settings.planner_mode,
            llm_provider=patch.llm_provider or self.global_settings.llm_provider,
            llm_model=patch.llm_model or self.global_settings.llm_model,
        )
        return self.get_user_llm_settings(user_id)


class FakeCoachingService(CoachingApplicationService):
    def __init__(self):
        super().__init__(
            settings=SimpleNamespace(garmin_email="runner@example.com", max_heart_rate=None),  # type: ignore[arg-type]
            user_state_service=SimpleNamespace(db=SimpleNamespace(ping=lambda: None)),  # type: ignore[arg-type]
        )
        self.last_sync = None
        self.feedback_calls = []

    def run_for_user_context(self, user_context, run_mode: str = "auto"):  # type: ignore[override]
        self.last_sync = (user_context.user_id, run_mode)
        return SimpleNamespace(status="completed", mode=run_mode)

    def record_feedback(self, user_context, feedback):  # type: ignore[override]
        self.feedback_calls.append((user_context.user_id, feedback.feedback_date))


def _service(
    *,
    schedule_times: str = "05:00,17:00",
    include_strength: bool = False,
) -> tuple[UserApplicationService, FakeAdminSettings, FakeCoachingService]:
    admin_settings = FakeAdminSettings()
    coaching_service = FakeCoachingService()
    service = UserApplicationService(
        user_service=FakeUserService(),
        admin_settings=admin_settings,  # type: ignore[arg-type]
        settings=SimpleNamespace(
            garmin_email="runner@example.com",
            schedule_times=schedule_times,
            include_strength=include_strength,
        ),
        coaching_service=coaching_service,
    )
    return service, admin_settings, coaching_service


def test_update_user_preferences_delegates_llm_overrides_to_admin_settings():
    service, admin_settings, _ = _service()

    profile = service.update_user_preferences(
        "user-1",
        UserPreferencesPatch(
            includeStrength=True,
            plannerMode="llm_driven",
            llmProvider="gemini",
            llmModel="gemini-2.5-pro",
        ),
    )

    assert profile.preferences.include_strength is True
    assert profile.llm_settings.planner_mode == "llm_driven"
    assert profile.llm_settings.llm_model == "gemini-2.5-pro"
    assert admin_settings.last_patch is not None


def test_ensure_local_runtime_user_context_uses_current_settings_defaults():
    service, _, _ = _service(schedule_times="06:00,18:00", include_strength=True)

    context = service.ensure_local_runtime_user_context()

    assert context.external_key == "runner@example.com"
    assert context.schedule_times == "06:00,18:00"
    assert context.include_strength is True


def test_run_user_sync_delegates_to_coaching_service():
    service, _, coaching_service = _service()

    response = service.run_user_sync("user-1", run_mode="plan")

    assert response.status == "completed"
    assert coaching_service.last_sync == ("user-1", "plan")


def test_record_feedback_delegates_to_coaching_service():
    service, _, coaching_service = _service()

    service.record_feedback(
        "user-1",
        SubjectiveFeedback.model_validate({"feedbackDate": "2026-04-24", "fatigueScore": 6}),
    )

    assert coaching_service.feedback_calls == [("user-1", date(2026, 4, 24))]
