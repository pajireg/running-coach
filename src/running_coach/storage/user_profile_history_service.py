"""User physiological profile time-series storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Optional, cast

from .database import DatabaseClient


@dataclass(frozen=True)
class UserProfileSnapshot:
    """A point-in-time snapshot of a user's physiological profile."""

    user_id: str
    effective_from: date
    max_heart_rate: int | None = None
    resting_heart_rate: int | None = None
    vo2_max: float | None = None
    lactate_threshold_pace: str | None = None
    lactate_threshold_heart_rate: int | None = None
    weight_kg: float | None = None
    height_cm: float | None = None
    source: str | None = None
    notes: str | None = None


class UserProfileHistoryService:
    """Persistence for user_profile_history time-series rows."""

    def __init__(self, db: DatabaseClient):
        self.db = db

    def record_snapshot(self, snapshot: UserProfileSnapshot) -> None:
        """Insert or update a snapshot for one (user_id, effective_from) pair."""
        self._execute(
            """
            INSERT INTO user_profile_history (
                user_id,
                effective_from,
                max_heart_rate,
                resting_heart_rate,
                vo2_max,
                lactate_threshold_pace,
                lactate_threshold_heart_rate,
                weight_kg,
                height_cm,
                source,
                notes
            )
            VALUES (
                %(user_id)s,
                %(effective_from)s,
                %(max_heart_rate)s,
                %(resting_heart_rate)s,
                %(vo2_max)s,
                %(lactate_threshold_pace)s,
                %(lactate_threshold_heart_rate)s,
                %(weight_kg)s,
                %(height_cm)s,
                %(source)s,
                %(notes)s
            )
            ON CONFLICT (user_id, effective_from)
            DO UPDATE SET
                max_heart_rate = EXCLUDED.max_heart_rate,
                resting_heart_rate = EXCLUDED.resting_heart_rate,
                vo2_max = EXCLUDED.vo2_max,
                lactate_threshold_pace = EXCLUDED.lactate_threshold_pace,
                lactate_threshold_heart_rate = EXCLUDED.lactate_threshold_heart_rate,
                weight_kg = EXCLUDED.weight_kg,
                height_cm = EXCLUDED.height_cm,
                source = EXCLUDED.source,
                notes = EXCLUDED.notes
            """,
            snapshot.__dict__,
        )

    def get_latest_profile(self, user_id: str) -> UserProfileSnapshot | None:
        """Return the most recent snapshot at or before today."""
        row = self._fetchone(
            """
            SELECT user_id, effective_from, max_heart_rate, resting_heart_rate,
                   vo2_max, lactate_threshold_pace, lactate_threshold_heart_rate,
                   weight_kg, height_cm, source, notes
            FROM user_profile_history
            WHERE user_id = %(user_id)s
            ORDER BY effective_from DESC
            LIMIT 1
            """,
            {"user_id": user_id},
        )
        if row is None:
            return None
        return UserProfileSnapshot(
            user_id=str(row["user_id"]),
            effective_from=row["effective_from"],
            max_heart_rate=row.get("max_heart_rate"),
            resting_heart_rate=row.get("resting_heart_rate"),
            vo2_max=self._float_or_none(row.get("vo2_max")),
            lactate_threshold_pace=row.get("lactate_threshold_pace"),
            lactate_threshold_heart_rate=row.get("lactate_threshold_heart_rate"),
            weight_kg=self._float_or_none(row.get("weight_kg")),
            height_cm=self._float_or_none(row.get("height_cm")),
            source=row.get("source"),
            notes=row.get("notes"),
        )

    @staticmethod
    def _float_or_none(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

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
