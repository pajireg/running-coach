"""Scheduled user job storage and next-run calculation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..models.user import UserContext, UserRecord
from .database import DatabaseClient


@dataclass(frozen=True)
class ClaimedUserJob:
    """A user job claimed by one worker lease."""

    user: UserRecord
    next_run_at: datetime


class ScheduledUserJobService:
    """Claim due scheduled users without scanning all users."""

    def __init__(self, db: DatabaseClient):
        self.db = db

    def upsert_for_user(
        self,
        user: UserRecord | UserContext,
        *,
        now: datetime | None = None,
    ) -> None:
        next_run_at = self.compute_next_run_at(
            timezone_name=user.timezone,
            schedule_times=user.schedule_times or "05:00,17:00",
            now=now,
        )
        self._execute(
            """
            INSERT INTO scheduled_user_jobs (
                athlete_id,
                next_run_at,
                failure_count,
                next_retry_at,
                last_error,
                disabled_at,
                updated_at
            )
            VALUES (
                %(user_id)s,
                %(next_run_at)s,
                0,
                NULL,
                NULL,
                NULL,
                NOW()
            )
            ON CONFLICT (athlete_id)
            DO UPDATE SET
                next_run_at = EXCLUDED.next_run_at,
                next_retry_at = NULL,
                disabled_at = NULL,
                updated_at = NOW()
            """,
            {"user_id": user.user_id, "next_run_at": next_run_at},
        )

    def claim_due_users(
        self,
        *,
        deployment_garmin_email: str | None,
        worker_id: str,
        batch_size: int = 25,
        lease_seconds: int = 900,
        now: datetime | None = None,
    ) -> list[ClaimedUserJob]:
        reference_time = now or datetime.now(timezone.utc)
        lease_until = reference_time + timedelta(seconds=lease_seconds)
        rows = self._fetchall(
            """
            WITH due AS (
                SELECT sj.athlete_id
                FROM scheduled_user_jobs sj
                JOIN athletes a ON a.athlete_id = sj.athlete_id
                WHERE sj.disabled_at IS NULL
                  AND sj.next_run_at <= %(now)s
                  AND (sj.next_retry_at IS NULL OR sj.next_retry_at <= %(now)s)
                  AND (sj.lease_until IS NULL OR sj.lease_until < %(now)s)
                  AND a.garmin_email IS NOT NULL
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
                ORDER BY sj.next_run_at ASC
                LIMIT %(batch_size)s
                FOR UPDATE SKIP LOCKED
            )
            UPDATE scheduled_user_jobs sj
            SET lease_until = %(lease_until)s,
                locked_by = %(worker_id)s,
                updated_at = NOW()
            FROM due
            JOIN athletes a ON a.athlete_id = due.athlete_id
            LEFT JOIN user_preferences up ON up.athlete_id = a.athlete_id
            WHERE sj.athlete_id = due.athlete_id
            RETURNING
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
                sj.next_run_at
            """,
            {
                "now": reference_time,
                "lease_until": lease_until,
                "worker_id": worker_id,
                "batch_size": batch_size,
                "deployment_garmin_email": deployment_garmin_email,
            },
        )
        return [
            ClaimedUserJob(
                user=UserRecord.from_row(row),
                next_run_at=cast(datetime, row["next_run_at"]),
            )
            for row in rows
        ]

    def complete_success(
        self,
        user: UserContext,
        *,
        now: datetime | None = None,
    ) -> None:
        reference_time = now or datetime.now(timezone.utc)
        next_run_at = self.compute_next_run_at(
            timezone_name=user.timezone,
            schedule_times=user.schedule_times,
            now=reference_time,
        )
        self._execute(
            """
            UPDATE scheduled_user_jobs
            SET next_run_at = %(next_run_at)s,
                lease_until = NULL,
                locked_by = NULL,
                last_run_at = %(now)s,
                last_status = 'completed',
                failure_count = 0,
                next_retry_at = NULL,
                last_error = NULL,
                updated_at = NOW()
            WHERE athlete_id = %(user_id)s
            """,
            {"user_id": user.user_id, "now": reference_time, "next_run_at": next_run_at},
        )

    def complete_failure(
        self,
        user: UserContext,
        *,
        error: str,
        now: datetime | None = None,
    ) -> None:
        reference_time = now or datetime.now(timezone.utc)
        self._execute(
            """
            UPDATE scheduled_user_jobs
            SET lease_until = NULL,
                locked_by = NULL,
                last_run_at = %(now)s,
                last_status = 'failed',
                failure_count = failure_count + 1,
                next_retry_at = %(next_retry_at)s,
                last_error = %(last_error)s,
                updated_at = NOW()
            WHERE athlete_id = %(user_id)s
            """,
            {
                "user_id": user.user_id,
                "now": reference_time,
                "next_retry_at": reference_time + self._backoff_for_failure(user.user_id),
                "last_error": error[:500],
            },
        )

    def compute_next_run_at(
        self,
        *,
        timezone_name: str,
        schedule_times: str,
        now: datetime | None = None,
    ) -> datetime:
        reference_time = now or datetime.now(timezone.utc)
        if reference_time.tzinfo is None:
            reference_time = reference_time.replace(tzinfo=timezone.utc)
        try:
            zone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            zone = ZoneInfo("UTC")

        local_now = reference_time.astimezone(zone)
        scheduled_times = self._parse_schedule_times(schedule_times)
        if not scheduled_times:
            scheduled_times = [(5, 0)]

        for day_offset in range(8):
            local_date = local_now.date() + timedelta(days=day_offset)
            for hour, minute in scheduled_times:
                candidate = datetime(
                    local_date.year,
                    local_date.month,
                    local_date.day,
                    hour,
                    minute,
                    tzinfo=zone,
                )
                if candidate > local_now:
                    return candidate.astimezone(timezone.utc)
        raise ValueError("Unable to compute next scheduled run")

    def _parse_schedule_times(self, raw_value: str) -> list[tuple[int, int]]:
        parsed: list[tuple[int, int]] = []
        for raw_time in [item.strip() for item in raw_value.split(",") if item.strip()]:
            if ":" in raw_time:
                hour_text, minute_text = raw_time.split(":", 1)
            else:
                hour_text, minute_text = raw_time, "00"
            try:
                hour = int(hour_text)
                minute = int(minute_text)
            except ValueError:
                continue
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                parsed.append((hour, minute))
        return sorted(set(parsed))

    def _backoff_for_failure(self, user_id: str) -> timedelta:
        row = self._fetchone(
            """
            SELECT failure_count
            FROM scheduled_user_jobs
            WHERE athlete_id = %(user_id)s
            """,
            {"user_id": user_id},
        )
        failure_count = int(row["failure_count"]) + 1 if row else 1
        if failure_count == 1:
            return timedelta(minutes=5)
        if failure_count == 2:
            return timedelta(minutes=15)
        if failure_count == 3:
            return timedelta(hours=1)
        return timedelta(hours=6)

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

    def _fetchone(self, query: str, params: dict[str, Any]) -> dict[str, Any] | None:
        rows = self._fetchall(query, params)
        return rows[0] if rows else None
