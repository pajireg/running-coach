"""관리자 LLM 설정 저장소 테스트."""

from __future__ import annotations

from typing import Any, Optional

from running_coach.models.llm_settings import (
    AdminLLMSettingsPatch,
    LLMSettings,
    UserLLMSettingsPatch,
)
from running_coach.storage.admin_settings import (
    KEY_MODEL,
    KEY_PLANNER_MODE,
    KEY_PROVIDER,
    AdminSettingsService,
)


class FakeAdminSettingsService(AdminSettingsService):
    def __init__(self):
        super().__init__(
            db=object(),  # type: ignore[arg-type]
            deployment_defaults=LLMSettings(
                planner_mode="legacy",
                llm_provider="gemini",
                llm_model="gemini-fallback",
            ),
        )
        self.system_settings: dict[str, str] = {}
        self.user_preferences: dict[str, dict[str, Optional[str]]] = {}

    def _execute(self, query: str, params: dict[str, Any]) -> None:  # type: ignore[override]
        if "system_settings" in query:
            self.system_settings[str(params["setting_key"])] = str(params["setting_value"])
            return
        self.user_preferences[str(params["user_id"])] = {
            "planner_mode": params["planner_mode"],
            "llm_provider": params["llm_provider"],
            "llm_model": params["llm_model"],
        }

    def _fetchall(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:  # type: ignore[override]
        if "system_settings" in query:
            keys = params["keys"]
            return [
                {"setting_key": key, "setting_value": value}
                for key, value in self.system_settings.items()
                if key in keys
            ]
        user_id = str(params["user_id"])
        row = self.user_preferences.get(user_id)
        return [row] if row else []


def test_global_llm_settings_fall_back_to_deployment_defaults():
    service = FakeAdminSettingsService()

    settings = service.get_global_llm_settings()

    assert settings.planner_mode == "legacy"
    assert settings.llm_provider == "gemini"
    assert settings.llm_model == "gemini-fallback"


def test_global_llm_settings_can_be_patched():
    service = FakeAdminSettingsService()

    settings = service.update_global_llm_settings(
        AdminLLMSettingsPatch(
            planner_mode="llm_driven",
            llm_provider="gemini",
            llm_model="gemini-3-pro",
        )
    )

    assert settings.planner_mode == "llm_driven"
    assert settings.llm_provider == "gemini"
    assert settings.llm_model == "gemini-3-pro"
    assert service.system_settings == {
        KEY_PLANNER_MODE: "llm_driven",
        KEY_PROVIDER: "gemini",
        KEY_MODEL: "gemini-3-pro",
    }


def test_user_override_resolution_and_clear():
    service = FakeAdminSettingsService()
    service.update_global_llm_settings(
        AdminLLMSettingsPatch(
            planner_mode="llm_driven",
            llm_provider="gemini",
            llm_model="gemini-3-flash",
        )
    )

    user_settings = service.update_user_llm_settings(
        "user-1",
        UserLLMSettingsPatch(llm_model="gemini-3-pro"),
    )

    assert user_settings.override_llm_model == "gemini-3-pro"
    assert user_settings.effective.planner_mode == "llm_driven"
    assert user_settings.effective.llm_provider == "gemini"
    assert user_settings.effective.llm_model == "gemini-3-pro"

    cleared = service.update_user_llm_settings(
        "user-1",
        UserLLMSettingsPatch(llm_model=None),
    )

    assert cleared.override_llm_model is None
    assert cleared.effective.llm_model == "gemini-3-flash"
