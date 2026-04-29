"""User-scoped coaching state storage."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional, cast

from ..models.feedback import SubjectiveFeedback
from .database import DatabaseClient


class UserCoachingStateService:
    """Persistence for user-owned coaching inputs and mutable runtime state."""

    def __init__(self, db: DatabaseClient):
        self.db = db

    def record_subjective_feedback(self, user_id: str, feedback: SubjectiveFeedback) -> None:
        self._execute(
            """
            INSERT INTO subjective_feedback (
                user_id,
                feedback_date,
                fatigue_score,
                soreness_score,
                stress_score,
                motivation_score,
                sleep_quality_score,
                pain_notes,
                notes
            )
            VALUES (
                %(user_id)s,
                %(feedback_date)s,
                %(fatigue_score)s,
                %(soreness_score)s,
                %(stress_score)s,
                %(motivation_score)s,
                %(sleep_quality_score)s,
                %(pain_notes)s,
                %(notes)s
            )
            ON CONFLICT (user_id, feedback_date)
            DO UPDATE SET
                fatigue_score = EXCLUDED.fatigue_score,
                soreness_score = EXCLUDED.soreness_score,
                stress_score = EXCLUDED.stress_score,
                motivation_score = EXCLUDED.motivation_score,
                sleep_quality_score = EXCLUDED.sleep_quality_score,
                pain_notes = EXCLUDED.pain_notes,
                notes = EXCLUDED.notes
            """,
            {
                "user_id": user_id,
                "feedback_date": feedback.feedback_date,
                "fatigue_score": feedback.fatigue_score,
                "soreness_score": feedback.soreness_score,
                "stress_score": feedback.stress_score,
                "motivation_score": feedback.motivation_score,
                "sleep_quality_score": feedback.sleep_quality_score,
                "pain_notes": feedback.pain_notes,
                "notes": feedback.notes,
            },
        )

    def upsert_availability_rule(
        self,
        user_id: str,
        *,
        weekday: int,
        is_available: bool,
        max_duration_minutes: int | None,
        preferred_session_type: str | None,
    ) -> None:
        self._execute(
            """
            INSERT INTO availability_rules (
                user_id,
                weekday,
                is_available,
                max_duration_minutes,
                preferred_session_type
            )
            VALUES (
                %(user_id)s,
                %(weekday)s,
                %(is_available)s,
                %(max_duration_minutes)s,
                %(preferred_session_type)s
            )
            ON CONFLICT (user_id, weekday)
            DO UPDATE SET
                is_available = EXCLUDED.is_available,
                max_duration_minutes = EXCLUDED.max_duration_minutes,
                preferred_session_type = EXCLUDED.preferred_session_type
            """,
            {
                "user_id": user_id,
                "weekday": weekday,
                "is_available": is_available,
                "max_duration_minutes": max_duration_minutes,
                "preferred_session_type": preferred_session_type,
            },
        )

    def upsert_training_block(
        self,
        user_id: str,
        *,
        phase: str,
        starts_on: date,
        ends_on: date,
        focus: str | None,
        weekly_volume_target_km: float | None,
    ) -> None:
        payload = {
            "user_id": user_id,
            "phase": phase,
            "starts_on": starts_on,
            "ends_on": ends_on,
            "focus": focus,
            "weekly_volume_target_km": weekly_volume_target_km,
        }
        self._execute(
            """
            DELETE FROM training_blocks
            WHERE user_id = %(user_id)s
              AND starts_on = %(starts_on)s
              AND ends_on = %(ends_on)s
            """,
            payload,
        )
        self._execute(
            """
            INSERT INTO training_blocks (
                user_id,
                phase,
                starts_on,
                ends_on,
                focus,
                weekly_volume_target_km
            )
            VALUES (
                %(user_id)s,
                %(phase)s,
                %(starts_on)s,
                %(ends_on)s,
                %(focus)s,
                %(weekly_volume_target_km)s
            )
            """,
            payload,
        )

    def upsert_race_goal(
        self,
        user_id: str,
        *,
        goal_name: str,
        race_date: date | None,
        distance: str | None,
        goal_time: str | None,
        target_pace: str | None,
        priority: int,
        is_active: bool = True,
    ) -> None:
        payload = {
            "user_id": user_id,
            "goal_name": goal_name,
            "race_date": race_date,
            "distance": distance,
            "goal_time": goal_time,
            "target_pace": target_pace,
            "priority": priority,
            "is_active": is_active,
        }
        self._execute(
            """
            UPDATE race_goals
            SET is_active = FALSE
            WHERE user_id = %(user_id)s
              AND priority = %(priority)s
            """,
            payload,
        )
        self._execute(
            """
            INSERT INTO race_goals (
                user_id,
                goal_name,
                race_date,
                distance,
                goal_time,
                target_pace,
                priority,
                is_active
            )
            VALUES (
                %(user_id)s,
                %(goal_name)s,
                %(race_date)s,
                %(distance)s,
                %(goal_time)s,
                %(target_pace)s,
                %(priority)s,
                %(is_active)s
            )
            """,
            payload,
        )

    def upsert_injury_status(
        self,
        user_id: str,
        *,
        status_date: date,
        injury_area: str,
        severity: int,
        notes: str | None,
        is_active: bool,
    ) -> None:
        self._execute(
            """
            INSERT INTO injury_status (
                user_id,
                status_date,
                injury_area,
                severity,
                notes,
                is_active
            )
            VALUES (
                %(user_id)s,
                %(status_date)s,
                %(injury_area)s,
                %(severity)s,
                %(notes)s,
                %(is_active)s
            )
            """,
            {
                "user_id": user_id,
                "status_date": status_date,
                "injury_area": injury_area,
                "severity": severity,
                "notes": notes,
                "is_active": is_active,
            },
        )

    def get_coaching_inputs(self, user_id: str) -> dict[str, list[dict[str, Any]]]:
        """Return app-facing user coaching inputs."""
        availability = self._fetchall(
            """
            SELECT
                weekday,
                is_available,
                max_duration_minutes,
                preferred_session_type
            FROM availability_rules
            WHERE user_id = %(user_id)s
            ORDER BY weekday ASC
            """,
            {"user_id": user_id},
        )
        goals = self._fetchall(
            """
            SELECT
                goal_name,
                race_date,
                distance,
                goal_time,
                target_pace,
                priority,
                is_active
            FROM race_goals
            WHERE user_id = %(user_id)s
            ORDER BY is_active DESC, priority ASC, created_at DESC
            """,
            {"user_id": user_id},
        )
        blocks = self._fetchall(
            """
            SELECT
                phase,
                starts_on,
                ends_on,
                focus,
                weekly_volume_target_km
            FROM training_blocks
            WHERE user_id = %(user_id)s
            ORDER BY starts_on DESC, ends_on DESC, created_at DESC
            """,
            {"user_id": user_id},
        )
        injuries = self._fetchall(
            """
            SELECT
                status_date,
                injury_area,
                severity,
                notes,
                is_active
            FROM injury_status
            WHERE user_id = %(user_id)s
            ORDER BY is_active DESC, status_date DESC, created_at DESC
            """,
            {"user_id": user_id},
        )
        return {
            "availability": availability,
            "goals": goals,
            "blocks": blocks,
            "injuries": injuries,
        }

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
