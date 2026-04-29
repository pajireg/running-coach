"""관리자 API 테스트."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from running_coach.api.admin import create_admin_router
from running_coach.models.llm_settings import (
    AdminLLMSettingsPatch,
    LLMSettings,
    UserLLMSettings,
    UserLLMSettingsPatch,
)
from running_coach.models.user import (
    AdminUserListResponse,
    AdminUserProvisionRequest,
    AdminUserSummary,
    IntegrationStatus,
    UserCreateResponse,
    UserPreferences,
    UserProfile,
)


class FakeAdminSettings:
    def __init__(self):
        self.global_settings = LLMSettings(
            planner_mode="legacy",
            llm_provider="gemini",
            llm_model="gemini-default",
        )
        self.user_settings = UserLLMSettings(
            user_id="user-1",
            effective=self.global_settings,
        )

    def get_global_llm_settings(self) -> LLMSettings:
        return self.global_settings

    def update_global_llm_settings(self, patch: AdminLLMSettingsPatch) -> LLMSettings:
        self.global_settings = LLMSettings(
            planner_mode=patch.planner_mode or self.global_settings.planner_mode,
            llm_provider=patch.llm_provider or self.global_settings.llm_provider,
            llm_model=patch.llm_model or self.global_settings.llm_model,
        )
        return self.global_settings

    def get_user_llm_settings(self, user_id: str) -> UserLLMSettings:
        self.user_settings.user_id = user_id
        return self.user_settings

    def update_user_llm_settings(
        self,
        user_id: str,
        patch: UserLLMSettingsPatch,
    ) -> UserLLMSettings:
        self.user_settings = UserLLMSettings(
            user_id=user_id,
            override_planner_mode=patch.planner_mode,
            override_llm_provider=patch.llm_provider,
            override_llm_model=patch.llm_model,
            effective=LLMSettings(
                planner_mode=patch.planner_mode or self.global_settings.planner_mode,
                llm_provider=patch.llm_provider or self.global_settings.llm_provider,
                llm_model=patch.llm_model or self.global_settings.llm_model,
            ),
        )
        return self.user_settings


class FakeUserApp:
    def __init__(self):
        self.last_payload: AdminUserProvisionRequest | None = None

    def provision_user(self, payload: AdminUserProvisionRequest) -> UserCreateResponse:
        self.last_payload = payload
        return UserCreateResponse(
            apiKey="rcu_admin_generated",
            user=UserProfile(
                userId="user-2",
                externalKey=payload.external_key or "generated-user",
                displayName=payload.display_name,
                preferences=UserPreferences(
                    timezone=payload.timezone,
                    locale=payload.locale,
                    scheduleTimes=payload.schedule_times,
                    runMode=payload.run_mode,
                    includeStrength=payload.include_strength,
                ),
                llmSettings=LLMSettings(
                    plannerMode="legacy",
                    llmProvider="gemini",
                    llmModel="gemini-default",
                ),
                integrationStatus=IntegrationStatus(
                    garmin="not_configured",
                    googleCalendar="disabled",
                ),
            ),
        )

    def list_admin_users(self) -> AdminUserListResponse:
        return AdminUserListResponse(
            users=[
                AdminUserSummary(
                    userId="user-1",
                    externalKey="runner@example.com",
                    displayName="Runner",
                    timezone="Asia/Seoul",
                    locale="ko",
                    scheduleTimes="05:00",
                    runMode="auto",
                    includeStrength=False,
                    activeApiKeyCount=2,
                    lastApiKeyUsedAt=None,
                    createdAt="2026-04-29T00:00:00Z",
                )
            ]
        )


def _client(
    api_key: str | None = "secret",
    user_app: FakeUserApp | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_admin_router(
            admin_settings=FakeAdminSettings(),  # type: ignore[arg-type]
            admin_api_key=api_key,
            user_app=user_app,  # type: ignore[arg-type]
        )
    )
    return TestClient(app)


def test_admin_llm_settings_requires_admin_key():
    client = _client()

    response = client.get("/admin/llm-settings")

    assert response.status_code == 401


def test_user_api_key_cannot_access_admin_settings():
    client = _client()

    response = client.get("/admin/llm-settings", headers={"Authorization": "Bearer user-key"})

    assert response.status_code == 401


def test_global_llm_settings_can_be_read_and_patched():
    client = _client()
    headers = {"Authorization": "Bearer secret"}

    response = client.patch(
        "/admin/llm-settings",
        headers=headers,
        json={
            "plannerMode": "llm_driven",
            "llmProvider": "gemini",
            "llmModel": "gemini-3-pro",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "plannerMode": "llm_driven",
        "llmProvider": "gemini",
        "llmModel": "gemini-3-pro",
    }


def test_user_override_endpoint_returns_effective_settings():
    client = _client()

    response = client.patch(
        "/admin/users/user-1/llm-settings",
        headers={"X-Admin-API-Key": "secret"},
        json={"llmModel": "gemini-3-pro"},
    )

    assert response.status_code == 200
    assert response.json()["overrides"]["llmModel"] == "gemini-3-pro"
    assert response.json()["effective"]["llmModel"] == "gemini-3-pro"


def test_admin_can_provision_user_api_key():
    user_app = FakeUserApp()
    client = _client(user_app=user_app)

    response = client.post(
        "/admin/users",
        headers={"Authorization": "Bearer secret"},
        json={
            "externalKey": "runner@example.com",
            "displayName": "Runner",
            "timezone": "Asia/Seoul",
            "locale": "ko",
            "scheduleTimes": "05:00",
            "runMode": "auto",
            "includeStrength": False,
            "keyName": "android-test",
        },
    )

    assert response.status_code == 201
    assert response.json()["apiKey"] == "rcu_admin_generated"
    assert response.json()["user"]["externalKey"] == "runner@example.com"
    assert user_app.last_payload is not None
    assert user_app.last_payload.key_name == "android-test"


def test_admin_can_list_users_without_exposing_key_hashes():
    client = _client(user_app=FakeUserApp())

    response = client.get(
        "/admin/users",
        headers={"Authorization": "Bearer secret"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["users"][0]["userId"] == "user-1"
    assert payload["users"][0]["activeApiKeyCount"] == 2
    assert "keyHash" not in payload["users"][0]
