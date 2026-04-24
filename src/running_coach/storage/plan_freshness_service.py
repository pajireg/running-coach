"""Read-side plan freshness persistence and replan trigger summary."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, cast

from ..config.constants import WORKOUT_SOURCE
from ..models.training import DailyPlan
from ..utils.logger import get_logger
from .athlete_scoped_store import AthleteScopedStore
from .database import DatabaseClient

logger = get_logger(__name__)

MEANINGFUL_MATCH_THRESHOLD = 0.75


class PlanFreshnessService(AthleteScopedStore):
    """Read service for active plan freshness and extension/replan triggers."""

    def __init__(self, db: DatabaseClient, athlete_key: str, timezone: str = "Asia/Seoul"):
        super().__init__(db=db, athlete_key=athlete_key, timezone=timezone)

    def list_planned_garmin_workout_ids(
        self,
        start_date: date,
        end_date: date,
    ) -> list[str]:
        """List persisted Garmin workout ids for a plan window."""
        rows = self._fetchall(
            """
            SELECT garmin_workout_id
            FROM planned_workouts
            WHERE athlete_id = %(athlete_id)s
              AND source = %(source)s
              AND workout_date BETWEEN %(start_date)s AND %(end_date)s
              AND garmin_workout_id IS NOT NULL
            """,
            {
                "athlete_id": self._athlete_id(),
                "source": WORKOUT_SOURCE,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        return [str(row["garmin_workout_id"]) for row in rows if row.get("garmin_workout_id")]

    def summarize_plan_freshness(self, as_of: date, horizon_days: int = 7) -> dict[str, Any]:
        """Summarize whether the current plan can be reused, extended, or regenerated."""
        athlete_id = self._athlete_id()
        end_date = as_of + timedelta(days=horizon_days - 1)
        plan_row = (
            self._fetchone(
                """
            SELECT COUNT(*) AS active_plan_days
            FROM planned_workouts
            WHERE athlete_id = %(athlete_id)s
              AND source = %(source)s
              AND workout_date BETWEEN %(as_of)s AND %(end_date)s
            """,
                {
                    "athlete_id": athlete_id,
                    "source": WORKOUT_SOURCE,
                    "as_of": as_of,
                    "end_date": end_date,
                },
            )
            or {}
        )
        decision_row = (
            self._fetchone(
                """
            SELECT created_at AS last_plan_created_at,
                   decision_date AS last_plan_decision_date,
                   rationale
            FROM coach_decisions
            WHERE athlete_id = %(athlete_id)s
              AND decision_type = 'daily_plan'
            ORDER BY created_at DESC
            LIMIT 1
            """,
                {"athlete_id": athlete_id},
            )
            or {}
        )
        metric_row = (
            self._fetchone(
                """
            SELECT
                metric_date,
                sleep_score,
                resting_hr,
                body_battery,
                hrv
            FROM daily_metrics
            WHERE athlete_id = %(athlete_id)s
              AND metric_date <= %(as_of)s
            ORDER BY metric_date DESC
            LIMIT 1
            """,
                {"athlete_id": athlete_id, "as_of": as_of},
            )
            or {}
        )
        activity_row = (
            self._fetchone(
                """
            SELECT MAX(created_at) AS latest_activity_created_at
            FROM activities
            WHERE athlete_id = %(athlete_id)s
            """,
                {"athlete_id": athlete_id},
            )
            or {}
        )

        active_plan_days = int(plan_row.get("active_plan_days") or 0)
        last_plan_created_at = decision_row.get("last_plan_created_at")
        last_plan_decision_date = decision_row.get("last_plan_decision_date")
        latest_activity_created_at = activity_row.get("latest_activity_created_at")
        latest_metric_date = metric_row.get("metric_date")
        recovery_shift_reasons = self._recovery_shift_reasons(
            decision_row=decision_row,
            metric_row=metric_row,
        )
        # Tolerate daily roll-over while preserving the last day of the plan window.
        has_active_plan = active_plan_days >= horizon_days - 1
        has_new_activity = (
            last_plan_created_at is not None
            and latest_activity_created_at is not None
            and latest_activity_created_at > last_plan_created_at
        )

        execution_row: dict[str, Any] = {}
        if has_new_activity and last_plan_created_at is not None:
            execution_row = (
                self._fetchone(
                    """
                SELECT we.target_match_score
                FROM workout_executions we
                JOIN activities a ON a.activity_id = we.activity_id
                WHERE we.athlete_id = %(athlete_id)s
                  AND we.planned_workout_id IS NOT NULL
                  AND a.created_at > %(since)s
                ORDER BY a.created_at DESC
                LIMIT 1
                """,
                    {"athlete_id": athlete_id, "since": last_plan_created_at},
                )
                or {}
            )
        latest_execution_score = execution_row.get("target_match_score")
        activity_is_normal_execution = (
            latest_execution_score is not None
            and float(latest_execution_score) >= MEANINGFUL_MATCH_THRESHOLD
        )

        has_significant_recovery_change = bool(recovery_shift_reasons)
        missed_start_date = as_of - timedelta(days=3)
        if last_plan_decision_date is not None:
            missed_start_date = max(missed_start_date, last_plan_decision_date)
        missed_end_date = as_of - timedelta(days=1)
        missed_row: dict[str, Any] = {}
        if missed_start_date <= missed_end_date:
            missed_row = (
                self._fetchone(
                    """
                SELECT
                    COUNT(*) AS missed_workout_count,
                    COUNT(*) FILTER (
                        WHERE
                            LOWER(pw.workout_name) LIKE '%%long%%'
                    ) AS missed_long_run_count,
                    COUNT(*) FILTER (
                        WHERE
                            LOWER(pw.workout_name) LIKE '%%tempo%%'
                            OR LOWER(pw.workout_name) LIKE '%%threshold%%'
                            OR LOWER(pw.workout_name) LIKE '%%interval%%'
                            OR pw.plan_payload::text ILIKE '%%Interval%%'
                    ) AS missed_quality_count,
                    COUNT(*) FILTER (
                        WHERE
                            LOWER(pw.workout_name) LIKE '%%recovery%%'
                    ) AS missed_recovery_count,
                    COUNT(*) FILTER (
                        WHERE
                            LOWER(pw.workout_name) NOT LIKE '%%long%%'
                            AND LOWER(pw.workout_name) NOT LIKE '%%tempo%%'
                            AND LOWER(pw.workout_name) NOT LIKE '%%threshold%%'
                            AND LOWER(pw.workout_name) NOT LIKE '%%interval%%'
                            AND LOWER(pw.workout_name) NOT LIKE '%%recovery%%'
                            AND pw.plan_payload::text NOT ILIKE '%%Interval%%'
                    ) AS missed_base_count,
                    COUNT(*) FILTER (
                        WHERE
                            LOWER(pw.workout_name) LIKE '%%long%%'
                            OR LOWER(pw.workout_name) LIKE '%%tempo%%'
                            OR LOWER(pw.workout_name) LIKE '%%threshold%%'
                            OR LOWER(pw.workout_name) LIKE '%%interval%%'
                            OR pw.plan_payload::text ILIKE '%%Interval%%'
                    ) AS missed_key_workout_count
                FROM planned_workouts pw
                LEFT JOIN workout_executions we
                  ON we.planned_workout_id = pw.planned_workout_id
                 AND we.target_match_score >= %(meaningful_match_threshold)s
                WHERE pw.athlete_id = %(athlete_id)s
                  AND pw.source = %(source)s
                  AND pw.workout_date BETWEEN %(missed_start_date)s AND %(missed_end_date)s
                  AND NOT pw.is_rest
                  AND we.workout_execution_id IS NULL
                """,
                    {
                        "athlete_id": athlete_id,
                        "source": WORKOUT_SOURCE,
                        "missed_start_date": missed_start_date,
                        "missed_end_date": missed_end_date,
                        "meaningful_match_threshold": MEANINGFUL_MATCH_THRESHOLD,
                    },
                )
                or {}
            )
        missed_workout_count = int(missed_row.get("missed_workout_count") or 0)
        missed_long_run_count = int(missed_row.get("missed_long_run_count") or 0)
        missed_quality_count = int(missed_row.get("missed_quality_count") or 0)
        missed_recovery_count = int(missed_row.get("missed_recovery_count") or 0)
        missed_base_count = int(missed_row.get("missed_base_count") or 0)
        missed_key_workout_count = int(missed_row.get("missed_key_workout_count") or 0)
        has_missed_planned_workout = missed_workout_count > 0
        has_missed_key_workout = missed_key_workout_count > 0
        has_missed_base_volume = missed_base_count >= 2
        should_replan_for_missed_workout = has_missed_key_workout or has_missed_base_volume

        should_extend_plan = (
            has_active_plan
            and has_new_activity
            and activity_is_normal_execution
            and not has_significant_recovery_change
            and not should_replan_for_missed_workout
            and last_plan_created_at is not None
        )
        should_generate_plan = (
            not has_active_plan
            or last_plan_created_at is None
            or (has_new_activity and not activity_is_normal_execution)
            or has_significant_recovery_change
            or should_replan_for_missed_workout
        )
        reasons = []
        if not has_active_plan:
            reasons.append("missing_active_plan")
        if last_plan_created_at is None:
            reasons.append("no_previous_plan_decision")
        if has_new_activity and not activity_is_normal_execution:
            reasons.append("new_activity_since_last_plan")
        if should_extend_plan:
            reasons.append("normal_execution_extend")
        if has_significant_recovery_change:
            reasons.append("significant_recovery_change")
        if has_missed_key_workout:
            reasons.append("missed_key_workout")
        elif has_missed_base_volume:
            reasons.append("missed_base_volume")

        return {
            "asOf": as_of.isoformat(),
            "horizonDays": horizon_days,
            "activePlanDays": active_plan_days,
            "hasActivePlan": has_active_plan,
            "lastPlanCreatedAt": (
                last_plan_created_at.isoformat() if last_plan_created_at else None
            ),
            "lastPlanDecisionDate": (
                last_plan_decision_date.isoformat() if last_plan_decision_date else None
            ),
            "latestActivityCreatedAt": (
                latest_activity_created_at.isoformat() if latest_activity_created_at else None
            ),
            "latestMetricDate": latest_metric_date.isoformat() if latest_metric_date else None,
            "hasNewActivitySinceLastPlan": has_new_activity,
            "hasSignificantRecoveryChange": has_significant_recovery_change,
            "recoveryShiftReasons": recovery_shift_reasons,
            "missedWorkoutCount": missed_workout_count,
            "missedRecoveryCount": missed_recovery_count,
            "missedBaseCount": missed_base_count,
            "missedQualityCount": missed_quality_count,
            "missedLongRunCount": missed_long_run_count,
            "missedKeyWorkoutCount": missed_key_workout_count,
            "hasMissedPlannedWorkout": has_missed_planned_workout,
            "hasMissedKeyWorkout": has_missed_key_workout,
            "shouldReplanForMissedWorkout": should_replan_for_missed_workout,
            "activityIsNormalExecution": activity_is_normal_execution,
            "shouldExtendPlan": should_extend_plan,
            "shouldGeneratePlan": should_generate_plan,
            "reasons": reasons,
        }

    def fetch_future_plan(self, from_date: date, days: int = 6) -> list[DailyPlan]:
        """Return planned workouts from from_date as DailyPlan models."""
        rows = self._fetchall(
            """
            SELECT workout_date, workout_name, is_rest, total_duration_seconds, plan_payload
            FROM planned_workouts
            WHERE athlete_id = %(athlete_id)s
              AND source = %(source)s
              AND workout_date >= %(from_date)s
            ORDER BY workout_date
            LIMIT %(days)s
            """,
            {
                "athlete_id": self._athlete_id(),
                "source": WORKOUT_SOURCE,
                "from_date": from_date,
                "days": days,
            },
        )
        result: list[DailyPlan] = []
        for row in rows:
            payload = row.get("plan_payload") or {}
            if isinstance(payload, str):
                payload = json.loads(payload)
            workout_data = dict(payload.get("workout") or {})
            workout_data.setdefault("workoutName", row["workout_name"])
            try:
                daily = DailyPlan.model_validate(
                    {
                        "date": (
                            row["workout_date"].isoformat()
                            if hasattr(row["workout_date"], "isoformat")
                            else str(row["workout_date"])
                        ),
                        "workout": workout_data,
                    }
                )
                result.append(daily)
            except Exception as exc:
                logger.warning(
                    "fetch_future_plan: %s 행 파싱 실패 (%s)", row.get("workout_date"), exc
                )
        return result

    def _recovery_shift_reasons(
        self,
        decision_row: dict[str, Any],
        metric_row: dict[str, Any],
    ) -> list[str]:
        """Reasons recovery data materially changed since the last plan."""
        if not decision_row or not metric_row:
            return []

        last_plan_decision_date = decision_row.get("last_plan_decision_date")
        latest_metric_date = metric_row.get("metric_date")
        if (
            last_plan_decision_date is not None
            and latest_metric_date is not None
            and latest_metric_date <= last_plan_decision_date
        ):
            return []

        rationale = cast(dict[str, Any], decision_row.get("rationale") or {})
        baseline_health = cast(dict[str, Any], rationale.get("health") or {})
        reasons: list[str] = []
        comparisons = [
            ("sleepScore", "sleep_score", -15, "sleep_score_drop"),
            ("bodyBattery", "body_battery", -20, "body_battery_drop"),
            ("hrv", "hrv", -12, "hrv_drop"),
        ]
        for baseline_key, current_key, drop_threshold, reason in comparisons:
            baseline = self._float_or_none(baseline_health.get(baseline_key))
            current = self._float_or_none(metric_row.get(current_key))
            if (
                baseline is not None
                and current is not None
                and current - baseline <= drop_threshold
            ):
                reasons.append(reason)

        baseline_resting_hr = self._float_or_none(baseline_health.get("restingHR"))
        current_resting_hr = self._float_or_none(metric_row.get("resting_hr"))
        if (
            baseline_resting_hr is not None
            and current_resting_hr is not None
            and current_resting_hr - baseline_resting_hr >= 7
        ):
            reasons.append("resting_hr_spike")

        return reasons
