"""관리자/system 설정 저장소."""

from __future__ import annotations

from typing import Any, Optional, cast

from ..models.llm_settings import (
    AdminLLMSettingsPatch,
    LLMSettings,
    UserLLMSettings,
    UserLLMSettingsPatch,
)
from .database import DatabaseClient

KEY_PLANNER_MODE = "llm.default_planner_mode"
KEY_PROVIDER = "llm.default_provider"
KEY_MODEL = "llm.default_model"


class AdminSettingsService:
    """관리자 설정 조회/수정 서비스."""

    def __init__(self, db: DatabaseClient, deployment_defaults: LLMSettings):
        self.db = db
        self.deployment_defaults = deployment_defaults

    def get_global_llm_settings(self) -> LLMSettings:
        rows = self._fetchall(
            """
            SELECT setting_key, setting_value
            FROM system_settings
            WHERE setting_key = ANY(%(keys)s)
            """,
            {"keys": [KEY_PLANNER_MODE, KEY_PROVIDER, KEY_MODEL]},
        )
        values = {str(row["setting_key"]): str(row["setting_value"]) for row in rows}
        return LLMSettings(
            planner_mode=values.get(KEY_PLANNER_MODE, self.deployment_defaults.planner_mode),
            llm_provider=values.get(KEY_PROVIDER, self.deployment_defaults.llm_provider),
            llm_model=values.get(KEY_MODEL, self.deployment_defaults.llm_model),
        )

    def update_global_llm_settings(self, patch: AdminLLMSettingsPatch) -> LLMSettings:
        update_values: dict[str, str] = {}
        if patch.planner_mode is not None:
            update_values[KEY_PLANNER_MODE] = patch.planner_mode
        if patch.llm_provider is not None:
            update_values[KEY_PROVIDER] = patch.llm_provider
        if patch.llm_model is not None:
            update_values[KEY_MODEL] = patch.llm_model.strip()

        for key, value in update_values.items():
            self._execute(
                """
                INSERT INTO system_settings (setting_key, setting_value, updated_at)
                VALUES (%(setting_key)s, %(setting_value)s, NOW())
                ON CONFLICT (setting_key)
                DO UPDATE SET
                    setting_value = EXCLUDED.setting_value,
                    updated_at = NOW()
                """,
                {"setting_key": key, "setting_value": value},
            )
        return self.get_global_llm_settings()

    def get_user_llm_settings(self, user_id: str) -> UserLLMSettings:
        global_settings = self.get_global_llm_settings()
        row = (
            self._fetchone(
                """
            SELECT planner_mode, llm_provider, llm_model
            FROM user_preferences
            WHERE athlete_id = %(user_id)s
            """,
                {"user_id": user_id},
            )
            or {}
        )
        override_planner_mode = row.get("planner_mode")
        override_provider = row.get("llm_provider")
        override_model = row.get("llm_model")
        effective = LLMSettings(
            planner_mode=override_planner_mode or global_settings.planner_mode,
            llm_provider=override_provider or global_settings.llm_provider,
            llm_model=override_model or global_settings.llm_model,
        )
        return UserLLMSettings(
            user_id=user_id,
            override_planner_mode=override_planner_mode,
            override_llm_provider=override_provider,
            override_llm_model=override_model,
            effective=effective,
        )

    def update_user_llm_settings(
        self,
        user_id: str,
        patch: UserLLMSettingsPatch,
    ) -> UserLLMSettings:
        current = self.get_user_llm_settings(user_id)
        fields_set = patch.model_fields_set
        planner_mode = (
            patch.planner_mode if "planner_mode" in fields_set else current.override_planner_mode
        )
        llm_provider = (
            patch.llm_provider if "llm_provider" in fields_set else current.override_llm_provider
        )
        llm_model = patch.llm_model if "llm_model" in fields_set else current.override_llm_model
        self._execute(
            """
            INSERT INTO user_preferences (
                athlete_id,
                planner_mode,
                llm_provider,
                llm_model,
                updated_at
            )
            VALUES (
                %(user_id)s,
                %(planner_mode)s,
                %(llm_provider)s,
                %(llm_model)s,
                NOW()
            )
            ON CONFLICT (athlete_id)
            DO UPDATE SET
                planner_mode = EXCLUDED.planner_mode,
                llm_provider = EXCLUDED.llm_provider,
                llm_model = EXCLUDED.llm_model,
                updated_at = NOW()
            """,
            {
                "user_id": user_id,
                "planner_mode": planner_mode,
                "llm_provider": llm_provider,
                "llm_model": llm_model.strip() if llm_model is not None else None,
            },
        )
        return self.get_user_llm_settings(user_id)

    def _execute(self, query: str, params: dict[str, Any]) -> None:
        with self.db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)

    def _fetchall(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                return cast(list[dict[str, Any]], list(cur.fetchall()))

    def _fetchone(self, query: str, params: dict[str, Any]) -> Optional[dict[str, Any]]:
        rows = self._fetchall(query, params)
        return rows[0] if rows else None
