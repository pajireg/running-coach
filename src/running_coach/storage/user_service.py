"""User identity, preferences, and API-key storage."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from hmac import compare_digest
from typing import Any, Optional, cast

from ..models.user import UserCreateRequest, UserPreferencesPatch, UserRecord
from .database import DatabaseClient

_USER_SELECT_COLUMNS = """
    u.user_id,
    u.external_key,
    u.display_name,
    u.timezone,
    u.locale,
    up.schedule_times,
    up.run_mode,
    up.include_strength,
    up.planner_mode,
    up.llm_provider,
    up.llm_model
"""


class UserService:
    """User-scoped identity and preference storage service."""

    def __init__(self, db: DatabaseClient):
        self.db = db

    def create_user(self, payload: UserCreateRequest) -> tuple[UserRecord, str]:
        external_key = payload.external_key or f"user-{uuid.uuid4()}"
        row = self._fetchone(
            """
            INSERT INTO users (
                external_key,
                display_name,
                timezone,
                locale
            )
            VALUES (
                %(external_key)s,
                %(display_name)s,
                %(timezone)s,
                %(locale)s
            )
            RETURNING user_id, external_key, display_name, timezone, locale
            """,
            {
                "external_key": external_key,
                "display_name": payload.display_name,
                "timezone": payload.timezone,
                "locale": payload.locale,
            },
        )
        if row is None:
            raise ValueError("Failed to create user")

        user_id = str(row["user_id"])
        self._upsert_preferences(
            user_id=user_id,
            schedule_times=payload.schedule_times,
            run_mode=payload.run_mode,
            include_strength=payload.include_strength,
        )
        record = self.get_user_record(user_id)
        raw_api_key = self.create_api_key(user_id=user_id, key_name="default")
        return record, raw_api_key

    def create_api_key(self, user_id: str, key_name: str = "default") -> str:
        raw_api_key = f"rcu_{secrets.token_urlsafe(32)}"
        key_hash = self._hash_api_key(raw_api_key)
        self._execute(
            """
            INSERT INTO user_api_keys (user_id, key_name, key_hash)
            VALUES (%(user_id)s, %(key_name)s, %(key_hash)s)
            """,
            {"user_id": user_id, "key_name": key_name, "key_hash": key_hash},
        )
        return raw_api_key

    def authenticate_api_key(self, api_key: str) -> Optional[UserRecord]:
        if not api_key:
            return None

        key_hash = self._hash_api_key(api_key)
        row = self._fetchone(
            f"""
            SELECT
                {_USER_SELECT_COLUMNS},
                uak.key_hash
            FROM user_api_keys uak
            JOIN users u ON u.user_id = uak.user_id
            LEFT JOIN user_preferences up ON up.user_id = u.user_id
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
            f"""
            SELECT {_USER_SELECT_COLUMNS}
            FROM users u
            LEFT JOIN user_preferences up ON up.user_id = u.user_id
            WHERE u.user_id = %(user_id)s
            """,
            {"user_id": user_id},
        )
        if row is None:
            raise KeyError(f"Unknown user: {user_id}")
        return UserRecord.from_row(row)

    def get_user_record_by_external_key(self, external_key: str) -> UserRecord | None:
        row = self._fetchone(
            f"""
            SELECT {_USER_SELECT_COLUMNS}
            FROM users u
            LEFT JOIN user_preferences up ON up.user_id = u.user_id
            WHERE u.external_key = %(external_key)s
            """,
            {"external_key": external_key},
        )
        if row is None:
            return None
        return UserRecord.from_row(row)

    def list_runnable_users(self) -> list[UserRecord]:
        """Return users runnable by the scheduled worker.

        A user is runnable when at least one training-data integration credential
        is active. The single-tenant deployment seeds this row at bootstrap from
        environment variables, so it appears here like any other user.
        """
        rows = self._fetchall(
            f"""
            SELECT {_USER_SELECT_COLUMNS}
            FROM users u
            LEFT JOIN user_preferences up ON up.user_id = u.user_id
            WHERE EXISTS (
                SELECT 1
                FROM user_integration_credentials uic
                WHERE uic.user_id = u.user_id
                  AND uic.provider = 'garmin'
                  AND uic.status = 'active'
            )
            ORDER BY u.created_at ASC, u.user_id ASC
            """,
            {},
        )
        return [UserRecord.from_row(row) for row in rows]

    def upsert_runtime_user(
        self,
        *,
        external_key: str,
        timezone: str,
        locale: str,
        schedule_times: str,
        run_mode: str,
        include_strength: bool,
        display_name: str | None = None,
    ) -> UserRecord:
        row = self._fetchone(
            """
            INSERT INTO users (
                external_key,
                display_name,
                timezone,
                locale
            )
            VALUES (
                %(external_key)s,
                %(display_name)s,
                %(timezone)s,
                %(locale)s
            )
            ON CONFLICT (external_key)
            DO UPDATE SET
                display_name = COALESCE(EXCLUDED.display_name, users.display_name),
                timezone = EXCLUDED.timezone,
                locale = EXCLUDED.locale,
                updated_at = NOW()
            RETURNING user_id
            """,
            {
                "external_key": external_key,
                "display_name": display_name,
                "timezone": timezone,
                "locale": locale,
            },
        )
        if row is None:
            raise ValueError(f"Failed to upsert runtime user: {external_key}")

        user_id = str(row["user_id"])
        self._upsert_preferences(
            user_id=user_id,
            schedule_times=schedule_times,
            run_mode=run_mode,
            include_strength=include_strength,
        )
        return self.get_user_record(user_id)

    def update_user_preferences(self, user_id: str, patch: UserPreferencesPatch) -> UserRecord:
        current = self.get_user_record(user_id)
        fields_set = patch.model_fields_set

        display_name = patch.display_name if "display_name" in fields_set else current.display_name
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
            UPDATE users
            SET
                display_name = %(display_name)s,
                timezone = %(timezone)s,
                locale = %(locale)s,
                updated_at = NOW()
            WHERE user_id = %(user_id)s
            """,
            {
                "user_id": user_id,
                "display_name": display_name,
                "timezone": timezone,
                "locale": locale,
            },
        )
        self._upsert_preferences(
            user_id=user_id,
            schedule_times=schedule_times,
            run_mode=run_mode,
            include_strength=include_strength,
        )
        return self.get_user_record(user_id)

    def _upsert_preferences(
        self,
        *,
        user_id: str,
        schedule_times: str | None,
        run_mode: str | None,
        include_strength: bool | None,
    ) -> None:
        self._execute(
            """
            INSERT INTO user_preferences (
                user_id,
                schedule_times,
                run_mode,
                include_strength,
                updated_at
            )
            VALUES (
                %(user_id)s,
                %(schedule_times)s,
                %(run_mode)s,
                %(include_strength)s,
                NOW()
            )
            ON CONFLICT (user_id)
            DO UPDATE SET
                schedule_times = EXCLUDED.schedule_times,
                run_mode = EXCLUDED.run_mode,
                include_strength = EXCLUDED.include_strength,
                updated_at = NOW()
            """,
            {
                "user_id": user_id,
                "schedule_times": schedule_times,
                "run_mode": run_mode,
                "include_strength": include_strength,
            },
        )

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
