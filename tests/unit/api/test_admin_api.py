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


def _client(api_key: str | None = "secret") -> TestClient:
    app = FastAPI()
    app.include_router(
        create_admin_router(
            admin_settings=FakeAdminSettings(),  # type: ignore[arg-type]
            admin_api_key=api_key,
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
