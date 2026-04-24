"""User identity, preferences, and API-key storage."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from hmac import compare_digest
from typing import Any, Optional, cast

from ..models.user import UserCreateRequest, UserPreferencesPatch, UserRecord
from .database import DatabaseClient


class UserService:
    """User-scoped identity and preference storage service."""

    def __init__(self, db: DatabaseClient):
        self.db = db

    def create_user(self, payload: UserCreateRequest) -> tuple[UserRecord, str]:
        external_key = payload.external_key or f"user-{uuid.uuid4()}"
        row = self._fetchone(
            """
            INSERT INTO athletes (
                external_key,
                display_name,
                garmin_email,
                timezone
            )
            VALUES (
                %(external_key)s,
                %(display_name)s,
                %(garmin_email)s,
                %(timezone)s
            )
            RETURNING athlete_id AS user_id, external_key, display_name, garmin_email, timezone
            """,
            {
                "external_key": external_key,
                "display_name": payload.display_name,
                "garmin_email": payload.garmin_email,
                "timezone": payload.timezone,
            },
        )
        if row is None:
            raise ValueError("Failed to create user")

        user_id = str(row["user_id"])
        self._execute(
            """
            INSERT INTO user_preferences (
                athlete_id,
                locale,
                schedule_times,
                run_mode,
                include_strength,
                updated_at
            )
            VALUES (
                %(user_id)s,
                %(locale)s,
                %(schedule_times)s,
                %(run_mode)s,
                %(include_strength)s,
                NOW()
            )
            ON CONFLICT (athlete_id)
            DO UPDATE SET
                locale = EXCLUDED.locale,
                schedule_times = EXCLUDED.schedule_times,
                run_mode = EXCLUDED.run_mode,
                include_strength = EXCLUDED.include_strength,
                updated_at = NOW()
            """,
            {
                "user_id": user_id,
                "locale": payload.locale,
                "schedule_times": payload.schedule_times,
                "run_mode": payload.run_mode,
                "include_strength": payload.include_strength,
            },
        )
        record = self.get_user_record(user_id)
        raw_api_key = self.create_api_key(user_id=user_id, key_name="default")
        return record, raw_api_key

    def create_api_key(self, user_id: str, key_name: str = "default") -> str:
        raw_api_key = f"rcu_{secrets.token_urlsafe(32)}"
        key_hash = self._hash_api_key(raw_api_key)
        self._execute(
            """
            INSERT INTO user_api_keys (
                athlete_id,
                key_name,
                key_hash
            )
            VALUES (
                %(user_id)s,
                %(key_name)s,
                %(key_hash)s
            )
            """,
            {"user_id": user_id, "key_name": key_name, "key_hash": key_hash},
        )
        return raw_api_key

    def authenticate_api_key(self, api_key: str) -> Optional[UserRecord]:
        if not api_key:
            return None

        key_hash = self._hash_api_key(api_key)
        row = self._fetchone(
            """
            SELECT
                a.athlete_id AS user_id,
                a.external_key,
                a.display_name,
                a.garmin_email,
                a.timezone,
                up.locale,
                up.schedule_times,
                up.run_mode,
                up.include_strength,
                up.planner_mode,
                up.llm_provider,
                up.llm_model,
                uak.key_hash
            FROM user_api_keys uak
            JOIN athletes a ON a.athlete_id = uak.athlete_id
            LEFT JOIN user_preferences up ON up.athlete_id = a.athlete_id
            WHERE uak.key_hash = %(key_hash)s
              AND uak.revoked_at IS NULL
            """,
            {"key_hash": key_hash},
        )
        if row is None:
            return None
        if not compare_digest(str(row["key_hash"]), key_hash):
            return None

        self._execute(
            """
            UPDATE user_api_keys
            SET last_used_at = NOW()
            WHERE key_hash = %(key_hash)s
            """,
            {"key_hash": key_hash},
        )
        return UserRecord.from_row(row)

    def get_user_record(self, user_id: str) -> UserRecord:
        row = self._fetchone(
            """
            SELECT
                a.athlete_id AS user_id,
                a.external_key,
                a.display_name,
                a.garmin_email,
                a.timezone,
                up.locale,
                up.schedule_times,
                up.run_mode,
                up.include_strength,
                up.planner_mode,
                up.llm_provider,
                up.llm_model
            FROM athletes a
            LEFT JOIN user_preferences up ON up.athlete_id = a.athlete_id
            WHERE a.athlete_id = %(user_id)s
            """,
            {"user_id": user_id},
        )
        if row is None:
            raise KeyError(f"Unknown user: {user_id}")
        return UserRecord.from_row(row)

    def get_user_record_by_external_key(self, external_key: str) -> UserRecord | None:
        row = self._fetchone(
            """
            SELECT
                a.athlete_id AS user_id,
                a.external_key,
                a.display_name,
                a.garmin_email,
                a.timezone,
                up.locale,
                up.schedule_times,
                up.run_mode,
                up.include_strength,
                up.planner_mode,
                up.llm_provider,
                up.llm_model
            FROM athletes a
            LEFT JOIN user_preferences up ON up.athlete_id = a.athlete_id
            WHERE a.external_key = %(external_key)s
            """,
            {"external_key": external_key},
        )
        if row is None:
            return None
        return UserRecord.from_row(row)

    def list_runnable_users(self, *, deployment_garmin_email: str | None) -> list[UserRecord]:
        """Return users that can be executed by the scheduled worker.

        The legacy deployment user remains runnable via env credentials. Additional
        users must have an active Garmin credential row so the worker does not pick
        up partially configured accounts.
        """
        rows = self._fetchall(
            """
            SELECT
                a.athlete_id AS user_id,
                a.external_key,
                a.display_name,
                a.garmin_email,
                a.timezone,
                up.locale,
                up.schedule_times,
                up.run_mode,
                up.include_strength,
                up.planner_mode,
                up.llm_provider,
                up.llm_model
            FROM athletes a
            LEFT JOIN user_preferences up ON up.athlete_id = a.athlete_id
            WHERE a.garmin_email IS NOT NULL
              AND (
                a.garmin_email = %(deployment_garmin_email)s
                OR EXISTS (
                    SELECT 1
                    FROM user_integration_credentials uic
                    WHERE uic.athlete_id = a.athlete_id
                      AND uic.provider = 'garmin'
                      AND uic.status = 'active'
                )
              )
            ORDER BY a.created_at ASC, a.athlete_id ASC
            """,
            {"deployment_garmin_email": deployment_garmin_email},
        )
        return [UserRecord.from_row(row) for row in rows]

    def upsert_runtime_user(
        self,
        *,
        external_key: str,
        garmin_email: str | None,
        timezone: str,
        locale: str,
        schedule_times: str,
        run_mode: str,
        include_strength: bool,
        display_name: str | None = None,
    ) -> UserRecord:
        row = self._fetchone(
            """
            INSERT INTO athletes (
                external_key,
                display_name,
                garmin_email,
                timezone
            )
            VALUES (
                %(external_key)s,
                %(display_name)s,
                %(garmin_email)s,
                %(timezone)s
            )
            ON CONFLICT (external_key)
            DO UPDATE SET
                display_name = COALESCE(EXCLUDED.display_name, athletes.display_name),
                garmin_email = EXCLUDED.garmin_email,
                timezone = EXCLUDED.timezone,
                updated_at = NOW()
            RETURNING athlete_id AS user_id
            """,
            {
                "external_key": external_key,
                "display_name": display_name,
                "garmin_email": garmin_email,
                "timezone": timezone,
            },
        )
        if row is None:
            raise ValueError(f"Failed to upsert runtime user: {external_key}")

        user_id = str(row["user_id"])
        self._execute(
            """
            INSERT INTO user_preferences (
                athlete_id,
                locale,
                schedule_times,
                run_mode,
                include_strength,
                updated_at
            )
            VALUES (
                %(user_id)s,
                %(locale)s,
                %(schedule_times)s,
                %(run_mode)s,
                %(include_strength)s,
                NOW()
            )
            ON CONFLICT (athlete_id)
            DO UPDATE SET
                locale = EXCLUDED.locale,
                schedule_times = EXCLUDED.schedule_times,
                run_mode = EXCLUDED.run_mode,
                include_strength = EXCLUDED.include_strength,
                updated_at = NOW()
            """,
            {
                "user_id": user_id,
                "locale": locale,
                "schedule_times": schedule_times,
                "run_mode": run_mode,
                "include_strength": include_strength,
            },
        )
        return self.get_user_record(user_id)

    def update_user_preferences(self, user_id: str, patch: UserPreferencesPatch) -> UserRecord:
        current = self.get_user_record(user_id)
        fields_set = patch.model_fields_set

        display_name = patch.display_name if "display_name" in fields_set else current.display_name
        garmin_email = patch.garmin_email if "garmin_email" in fields_set else current.garmin_email
        timezone = patch.timezone if "timezone" in fields_set else current.timezone
        locale = patch.locale if "locale" in fields_set else current.locale
        schedule_times = (
            patch.schedule_times if "schedule_times" in fields_set else current.schedule_times
        )
        run_mode = patch.run_mode if "run_mode" in fields_set else current.run_mode
        include_strength = (
            patch.include_strength
            if "include_strength" in fields_set
            else current.include_strength or False
        )

        self._execute(
            """
            UPDATE athletes
            SET
                display_name = %(display_name)s,
                garmin_email = %(garmin_email)s,
                timezone = %(timezone)s,
                updated_at = NOW()
            WHERE athlete_id = %(user_id)s
            """,
            {
                "user_id": user_id,
                "display_name": display_name,
                "garmin_email": garmin_email,
                "timezone": timezone,
            },
        )
        self._execute(
            """
            INSERT INTO user_preferences (
                athlete_id,
                locale,
                schedule_times,
                run_mode,
                include_strength,
                updated_at
            )
            VALUES (
                %(user_id)s,
                %(locale)s,
                %(schedule_times)s,
                %(run_mode)s,
                %(include_strength)s,
                NOW()
            )
            ON CONFLICT (athlete_id)
            DO UPDATE SET
                locale = EXCLUDED.locale,
                schedule_times = EXCLUDED.schedule_times,
                run_mode = EXCLUDED.run_mode,
                include_strength = EXCLUDED.include_strength,
                updated_at = NOW()
            """,
            {
                "user_id": user_id,
                "locale": locale,
                "schedule_times": schedule_times,
                "run_mode": run_mode,
                "include_strength": include_strength,
            },
        )
        return self.get_user_record(user_id)

    def _hash_api_key(self, api_key: str) -> str:
        return hashlib.sha256(api_key.encode("utf-8")).hexdigest()

    def _execute(self, query: str, params: dict[str, Any]) -> None:
        with self.db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)

    def _fetchone(self, query: str, params: dict[str, Any]) -> Optional[dict[str, Any]]:
        with self.db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone()
                return cast(Optional[dict[str, Any]], row)

    def _fetchall(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
                return cast(list[dict[str, Any]], list(rows))
