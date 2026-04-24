"""User service storage tests."""

from __future__ import annotations

from typing import Any, Optional

from running_coach.models.user import UserCreateRequest, UserPreferencesPatch
from running_coach.storage.user_service import UserService


class FakeUserService(UserService):
    def __init__(self):
        super().__init__(db=object())  # type: ignore[arg-type]
        self.users: dict[str, dict[str, Any]] = {}
        self.api_keys: dict[str, str] = {}
        self.next_id = 1

    def create_user(self, payload: UserCreateRequest) -> tuple[Any, str]:  # type: ignore[override]
        user_id = f"user-{self.next_id}"
        self.next_id += 1
        external_key = payload.external_key or f"runner-{self.next_id}"
        row = {
            "user_id": user_id,
            "external_key": external_key,
            "display_name": payload.display_name,
            "garmin_email": payload.garmin_email,
            "timezone": payload.timezone,
            "locale": payload.locale,
            "schedule_times": payload.schedule_times,
            "include_strength": payload.include_strength,
            "planner_mode": None,
            "llm_provider": None,
            "llm_model": None,
        }
        self.users[user_id] = row
        api_key = self.create_api_key(user_id)
        return self.get_user_record(user_id), api_key

    def create_api_key(self, user_id: str, key_name: str = "default") -> str:  # type: ignore[override]
        api_key = f"rcu_{user_id}"
        self.api_keys[self._hash_api_key(api_key)] = user_id
        return api_key

    def authenticate_api_key(self, api_key: str) -> Optional[Any]:  # type: ignore[override]
        user_id = self.api_keys.get(self._hash_api_key(api_key))
        if user_id is None:
            return None
        return self.get_user_record(user_id)

    def get_user_record(self, user_id: str):  # type: ignore[override]
        from running_coach.models.user import UserRecord

        row = self.users.get(user_id)
        if row is None:
            raise KeyError(user_id)
        return UserRecord.from_row(row)

    def get_user_record_by_external_key(self, external_key: str):  # type: ignore[override]
        for row in self.users.values():
            if row["external_key"] == external_key:
                from running_coach.models.user import UserRecord

                return UserRecord.from_row(row)
        return None

    def upsert_runtime_user(  # type: ignore[override]
        self,
        *,
        external_key: str,
        garmin_email: str | None,
        timezone: str,
        locale: str,
        schedule_times: str,
        include_strength: bool,
        display_name: str | None = None,
    ):
        existing = self.get_user_record_by_external_key(external_key)
        if existing is None:
            user_id = f"user-{self.next_id}"
            self.next_id += 1
            self.users[user_id] = {
                "user_id": user_id,
                "external_key": external_key,
                "display_name": display_name,
                "garmin_email": garmin_email,
                "timezone": timezone,
                "locale": locale,
                "schedule_times": schedule_times,
                "include_strength": include_strength,
                "planner_mode": None,
                "llm_provider": None,
                "llm_model": None,
            }
            return self.get_user_record(user_id)

        row = self.users[existing.user_id]
        row["display_name"] = display_name or row["display_name"]
        row["garmin_email"] = garmin_email
        row["timezone"] = timezone
        row["locale"] = locale
        row["schedule_times"] = schedule_times
        row["include_strength"] = include_strength
        return self.get_user_record(existing.user_id)

    def update_user_preferences(self, user_id: str, patch: UserPreferencesPatch):  # type: ignore[override]
        row = self.users[user_id]
        if "display_name" in patch.model_fields_set:
            row["display_name"] = patch.display_name
        if "locale" in patch.model_fields_set:
            row["locale"] = patch.locale
        if "schedule_times" in patch.model_fields_set:
            row["schedule_times"] = patch.schedule_times
        if "include_strength" in patch.model_fields_set:
            row["include_strength"] = patch.include_strength
        return self.get_user_record(user_id)


class QueryCaptureUserService(UserService):
    def __init__(self):
        super().__init__(db=object())  # type: ignore[arg-type]
        self.last_query = ""
        self.last_params: dict[str, Any] = {}

    def _fetchall(self, query: str, params: dict[str, Any]):  # type: ignore[override]
        self.last_query = query
        self.last_params = params
        return [
            {
                "user_id": "user-1",
                "external_key": "runner-1",
                "display_name": "Runner One",
                "garmin_email": "runner@example.com",
                "timezone": "Asia/Seoul",
                "locale": "ko",
                "schedule_times": "05:00,17:00",
                "include_strength": False,
                "planner_mode": None,
                "llm_provider": None,
                "llm_model": None,
            }
        ]


def test_create_user_returns_api_key_and_record():
    service = FakeUserService()

    record, api_key = service.create_user(
        UserCreateRequest(
            externalKey="runner-1",
            displayName="Runner One",
            garminEmail="runner@example.com",
        )
    )

    assert record.user_id == "user-1"
    assert record.external_key == "runner-1"
    assert api_key == "rcu_user-1"


def test_authenticate_api_key_returns_user_record():
    service = FakeUserService()
    service.create_user(UserCreateRequest(displayName="Runner One"))

    record = service.authenticate_api_key("rcu_user-1")

    assert record is not None
    assert record.user_id == "user-1"


def test_update_user_preferences_updates_stored_values():
    service = FakeUserService()
    service.create_user(UserCreateRequest(displayName="Runner One"))

    record = service.update_user_preferences(
        "user-1",
        UserPreferencesPatch(
            locale="en",
            includeStrength=True,
        ),
    )

    assert record.locale == "en"
    assert record.include_strength is True
    assert record.planner_mode is None
    assert record.llm_model is None


def test_upsert_runtime_user_reuses_external_key():
    service = FakeUserService()
    first = service.upsert_runtime_user(
        external_key="legacy-user",
        display_name=None,
        garmin_email="runner@example.com",
        timezone="Asia/Seoul",
        locale="ko",
        schedule_times="05:00,17:00",
        include_strength=False,
    )

    updated = service.upsert_runtime_user(
        external_key="legacy-user",
        display_name="Local Runner",
        garmin_email="runner@example.com",
        timezone="Asia/Seoul",
        locale="en",
        schedule_times="06:00",
        include_strength=True,
    )

    assert updated.user_id == first.user_id
    assert updated.display_name == "Local Runner"
    assert updated.locale == "en"
    assert updated.schedule_times == "06:00"
    assert updated.include_strength is True


def test_list_runnable_users_uses_env_or_active_garmin_credential_filter():
    service = QueryCaptureUserService()

    records = service.list_runnable_users(deployment_garmin_email="runner@example.com")

    assert [record.user_id for record in records] == ["user-1"]
    assert service.last_params == {"deployment_garmin_email": "runner@example.com"}
    assert "uic.provider = 'garmin'" in service.last_query
    assert "uic.status = 'active'" in service.last_query
