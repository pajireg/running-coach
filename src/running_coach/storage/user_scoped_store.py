"""Shared DB helpers for user-scoped persistence services."""

from __future__ import annotations

from typing import Any, Optional, cast

from .database import DatabaseClient


class UserScopedStore:
    """Base class for storage services scoped to one user row."""

    def __init__(self, db: DatabaseClient, external_key: str, timezone: str = "Asia/Seoul"):
        self.db = db
        self.external_key = external_key
        self.timezone = timezone

    def _user_id(self) -> str:
        query = "SELECT user_id FROM users WHERE external_key = %(external_key)s"
        rows = self._fetchall(query, {"external_key": self.external_key})
        if not rows:
            raise ValueError("User must be created before reading or writing history")
        return str(rows[0]["user_id"])

    def _execute(self, query: str, params: dict[str, Any]) -> None:
        with self.db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)

    def _fetchall(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
                return cast(list[dict[str, Any]], list(rows))

    def _fetchone(self, query: str, params: dict[str, Any]) -> Optional[dict[str, Any]]:
        rows = self._fetchall(query, params)
        return rows[0] if rows else None

    @staticmethod
    def _float_or_none(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
