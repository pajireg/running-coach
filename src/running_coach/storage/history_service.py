"""훈련 히스토리 영속화 서비스."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any, Optional, cast
from zoneinfo import ZoneInfo

from ..config.constants import TIMEZONE, WORKOUT_SOURCE
from ..models.feedback import SubjectiveFeedback
from ..models.metrics import AdvancedMetrics
from ..models.training import DailyPlan, TrainingPlan
from ..utils.logger import get_logger
from .database import DatabaseClient

logger = get_logger(__name__)

RUNNING_SPORT_TYPES = {"running", "treadmill_running", "trail_running"}
MEANINGFUL_MATCH_THRESHOLD = 0.75
PLANNED_MATCH_SELECTION_THRESHOLD = 0.7


class CoachingHistoryService:
    """전문 코치용 장기 히스토리 저장."""

    def __init__(self, db: DatabaseClient, athlete_key: str, timezone: str = "Asia/Seoul"):
        self.db = db
        self.athlete_key = athlete_key
        self.timezone = timezone

    def ensure_athlete(self, garmin_email: str, max_heart_rate: Optional[int]) -> None:
        """선수 레코드 upsert."""
        query = """
            INSERT INTO athletes (external_key, garmin_email, timezone, max_heart_rate)
            VALUES (%(external_key)s, %(garmin_email)s, %(timezone)s, %(max_heart_rate)s)
            ON CONFLICT (external_key)
            DO UPDATE SET
                garmin_email = EXCLUDED.garmin_email,
                timezone = EXCLUDED.timezone,
                max_heart_rate = EXCLUDED.max_heart_rate,
                updated_at = NOW()
        """
        self._execute(
            query,
            {
                "external_key": self.athlete_key,
                "garmin_email": garmin_email,
                "timezone": self.timezone,
                "max_heart_rate": max_heart_rate,
            },
        )

    def record_daily_metrics(self, metrics: AdvancedMetrics) -> None:
        """일일 코칭 메트릭 저장."""
        payload = {
            "metric_date": metrics.date,
            "steps": metrics.health.steps,
            "sleep_score": metrics.health.sleep_score,
            "resting_hr": metrics.health.resting_hr,
            "body_battery": metrics.health.body_battery,
            "hrv": metrics.health.hrv,
            "vo2_max": metrics.performance.vo2_max,
            "lactate_threshold_pace": (
                metrics.performance.lactate_threshold.pace
                if metrics.performance.lactate_threshold
                else None
            ),
            "lactate_threshold_heart_rate": (
                metrics.performance.lactate_threshold.heart_rate
                if metrics.performance.lactate_threshold
                else None
            ),
            "training_status": metrics.performance.training_load.status,
            "load_balance_phrase": metrics.performance.training_load.balance_phrase,
            "acute_load": metrics.performance.training_load.acute_load,
            "chronic_load": metrics.performance.training_load.chronic_load,
            "acwr": metrics.performance.training_load.acwr,
            "recent_7d_run_distance_km": metrics.context.recent_7d_run_distance_km,
            "recent_30d_run_distance_km": metrics.context.recent_30d_run_distance_km,
            "recent_30d_run_count": metrics.context.recent_30d_run_count,
            "health_payload": json.dumps(metrics.health.to_dict(), ensure_ascii=False),
            "performance_payload": json.dumps(metrics.performance.to_dict(), ensure_ascii=False),
            "context_payload": json.dumps(metrics.context.to_dict(), ensure_ascii=False),
        }

        query = """
            INSERT INTO daily_metrics (
                athlete_id,
                metric_date,
                steps,
                sleep_score,
                resting_hr,
                body_battery,
                hrv,
                vo2_max,
                lactate_threshold_pace,
                lactate_threshold_heart_rate,
                training_status,
                load_balance_phrase,
                acute_load,
                chronic_load,
                acwr,
                recent_7d_run_distance_km,
                recent_30d_run_distance_km,
                recent_30d_run_count,
                health_payload,
                performance_payload,
                context_payload
            )
            VALUES (
                %(athlete_id)s,
                %(metric_date)s,
                %(steps)s,
                %(sleep_score)s,
                %(resting_hr)s,
                %(body_battery)s,
                %(hrv)s,
                %(vo2_max)s,
                %(lactate_threshold_pace)s,
                %(lactate_threshold_heart_rate)s,
                %(training_status)s,
                %(load_balance_phrase)s,
                %(acute_load)s,
                %(chronic_load)s,
                %(acwr)s,
                %(recent_7d_run_distance_km)s,
                %(recent_30d_run_distance_km)s,
                %(recent_30d_run_count)s,
                %(health_payload)s::jsonb,
                %(performance_payload)s::jsonb,
                %(context_payload)s::jsonb
            )
            ON CONFLICT (athlete_id, metric_date)
            DO UPDATE SET
                steps = EXCLUDED.steps,
                sleep_score = EXCLUDED.sleep_score,
                resting_hr = EXCLUDED.resting_hr,
                body_battery = EXCLUDED.body_battery,
                hrv = EXCLUDED.hrv,
                vo2_max = EXCLUDED.vo2_max,
                lactate_threshold_pace = EXCLUDED.lactate_threshold_pace,
                lactate_threshold_heart_rate = EXCLUDED.lactate_threshold_heart_rate,
                training_status = EXCLUDED.training_status,
                load_balance_phrase = EXCLUDED.load_balance_phrase,
                acute_load = EXCLUDED.acute_load,
                chronic_load = EXCLUDED.chronic_load,
                acwr = EXCLUDED.acwr,
                recent_7d_run_distance_km = EXCLUDED.recent_7d_run_distance_km,
                recent_30d_run_distance_km = EXCLUDED.recent_30d_run_distance_km,
                recent_30d_run_count = EXCLUDED.recent_30d_run_count,
                health_payload = EXCLUDED.health_payload,
                performance_payload = EXCLUDED.performance_payload,
                context_payload = EXCLUDED.context_payload
        """
        self._execute(query, {"athlete_id": self._athlete_id(), **payload})

    def record_training_plan(self, plan: TrainingPlan) -> None:
        """7일 계획 저장."""
        athlete_id = self._athlete_id()
        delete_query = """
            DELETE FROM planned_workouts
            WHERE athlete_id = %(athlete_id)s
              AND workout_date BETWEEN %(start_date)s AND %(end_date)s
              AND source = %(source)s
        """
        self._execute(
            delete_query,
            {
                "athlete_id": athlete_id,
                "start_date": plan.start_date,
                "end_date": plan.end_date,
                "source": WORKOUT_SOURCE,
            },
        )

        insert_query = """
            INSERT INTO planned_workouts (
                athlete_id,
                workout_date,
                source,
                workout_name,
                description,
                sport_type,
                is_rest,
                total_duration_seconds,
                plan_payload
            )
            VALUES (
                %(athlete_id)s,
                %(workout_date)s,
                %(source)s,
                %(workout_name)s,
                %(description)s,
                %(sport_type)s,
                %(is_rest)s,
                %(total_duration_seconds)s,
                %(plan_payload)s::jsonb
            )
        """
        for day in plan.plan:
            self._execute(
                insert_query,
                {
                    "athlete_id": athlete_id,
                    "workout_date": day.date,
                    "workout_name": day.workout.workout_name,
                    "source": WORKOUT_SOURCE,
                    "description": day.workout.description,
                    "sport_type": day.workout.sport_type,
                    "is_rest": day.workout.is_rest,
                    "total_duration_seconds": day.workout.total_duration,
                    "plan_payload": json.dumps(self._serialize_daily_plan(day), ensure_ascii=False),
                },
            )

    def record_subjective_feedback(self, feedback: SubjectiveFeedback) -> None:
        """주관 피드백 upsert."""
        query = """
            INSERT INTO subjective_feedback (
                athlete_id,
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
                %(athlete_id)s,
                %(feedback_date)s,
                %(fatigue_score)s,
                %(soreness_score)s,
                %(stress_score)s,
                %(motivation_score)s,
                %(sleep_quality_score)s,
                %(pain_notes)s,
                %(notes)s
            )
            ON CONFLICT (athlete_id, feedback_date)
            DO UPDATE SET
                fatigue_score = EXCLUDED.fatigue_score,
                soreness_score = EXCLUDED.soreness_score,
                stress_score = EXCLUDED.stress_score,
                motivation_score = EXCLUDED.motivation_score,
                sleep_quality_score = EXCLUDED.sleep_quality_score,
                pain_notes = EXCLUDED.pain_notes,
                notes = EXCLUDED.notes
        """
        self._execute(
            query,
            {
                "athlete_id": self._athlete_id(),
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
        weekday: int,
        is_available: bool = True,
        max_duration_minutes: Optional[int] = None,
        preferred_session_type: Optional[str] = None,
    ) -> None:
        """요일별 훈련 가능 조건 upsert."""
        query = """
            INSERT INTO availability_rules (
                athlete_id,
                weekday,
                is_available,
                max_duration_minutes,
                preferred_session_type
            )
            VALUES (
                %(athlete_id)s,
                %(weekday)s,
                %(is_available)s,
                %(max_duration_minutes)s,
                %(preferred_session_type)s
            )
            ON CONFLICT (athlete_id, weekday)
            DO UPDATE SET
                is_available = EXCLUDED.is_available,
                max_duration_minutes = EXCLUDED.max_duration_minutes,
                preferred_session_type = EXCLUDED.preferred_session_type
        """
        self._execute(
            query,
            {
                "athlete_id": self._athlete_id(),
                "weekday": weekday,
                "is_available": is_available,
                "max_duration_minutes": max_duration_minutes,
                "preferred_session_type": preferred_session_type,
            },
        )

    def upsert_training_block(
        self,
        phase: str,
        starts_on: date,
        ends_on: date,
        focus: Optional[str] = None,
        weekly_volume_target_km: Optional[float] = None,
    ) -> None:
        """훈련 블록 upsert."""
        delete_query = """
            DELETE FROM training_blocks
            WHERE athlete_id = %(athlete_id)s
              AND starts_on = %(starts_on)s
              AND ends_on = %(ends_on)s
        """
        insert_query = """
            INSERT INTO training_blocks (
                athlete_id,
                phase,
                starts_on,
                ends_on,
                focus,
                weekly_volume_target_km
            )
            VALUES (
                %(athlete_id)s,
                %(phase)s,
                %(starts_on)s,
                %(ends_on)s,
                %(focus)s,
                %(weekly_volume_target_km)s
            )
        """
        payload = {
            "athlete_id": self._athlete_id(),
            "phase": phase,
            "starts_on": starts_on,
            "ends_on": ends_on,
            "focus": focus,
            "weekly_volume_target_km": weekly_volume_target_km,
        }
        self._execute(delete_query, payload)
        self._execute(insert_query, payload)

    def upsert_race_goal(
        self,
        goal_name: str,
        race_date: Optional[date],
        distance: Optional[str],
        goal_time: Optional[str],
        target_pace: Optional[str],
        priority: int = 1,
        is_active: bool = True,
    ) -> None:
        """주요 레이스 목표 upsert."""
        deactivate_query = """
            UPDATE race_goals
            SET is_active = FALSE
            WHERE athlete_id = %(athlete_id)s
              AND priority = %(priority)s
        """
        insert_query = """
            INSERT INTO race_goals (
                athlete_id,
                goal_name,
                race_date,
                distance,
                goal_time,
                target_pace,
                priority,
                is_active
            )
            VALUES (
                %(athlete_id)s,
                %(goal_name)s,
                %(race_date)s,
                %(distance)s,
                %(goal_time)s,
                %(target_pace)s,
                %(priority)s,
                %(is_active)s
            )
        """
        payload = {
            "athlete_id": self._athlete_id(),
            "goal_name": goal_name,
            "race_date": race_date,
            "distance": distance,
            "goal_time": goal_time,
            "target_pace": target_pace,
            "priority": priority,
            "is_active": is_active,
        }
        self._execute(deactivate_query, payload)
        self._execute(insert_query, payload)

    def upsert_injury_status(
        self,
        status_date: date,
        injury_area: str,
        severity: int,
        notes: Optional[str] = None,
        is_active: bool = True,
    ) -> None:
        """부상 상태 upsert."""
        query = """
            INSERT INTO injury_status (
                athlete_id,
                status_date,
                injury_area,
                severity,
                notes,
                is_active
            )
            VALUES (
                %(athlete_id)s,
                %(status_date)s,
                %(injury_area)s,
                %(severity)s,
                %(notes)s,
                %(is_active)s
            )
        """
        self._execute(
            query,
            {
                "athlete_id": self._athlete_id(),
                "status_date": status_date,
                "injury_area": injury_area,
                "severity": severity,
                "notes": notes,
                "is_active": is_active,
            },
        )

    def record_garmin_sync_result(
        self,
        workout_date: date,
        garmin_workout_id: Optional[str],
        garmin_schedule_status: str,
    ) -> None:
        """Garmin 업로드/예약 결과를 planned_workouts에 기록."""
        query = """
            UPDATE planned_workouts
            SET
                garmin_workout_id = %(garmin_workout_id)s,
                garmin_schedule_status = %(garmin_schedule_status)s
            WHERE athlete_id = %(athlete_id)s
              AND workout_date = %(workout_date)s
              AND source = %(source)s
        """
        self._execute(
            query,
            {
                "athlete_id": self._athlete_id(),
                "workout_date": workout_date,
                "garmin_workout_id": garmin_workout_id,
                "garmin_schedule_status": garmin_schedule_status[:100],
                "source": WORKOUT_SOURCE,
            },
        )

    def backfill_planned_workouts(self, scheduled_items: list[dict[str, Any]]) -> int:
        """Garmin 캘린더의 과거 Running Coach 워크아웃을 planned_workouts로 백필."""
        athlete_id = self._athlete_id()
        inserted = 0
        query = """
            INSERT INTO planned_workouts (
                athlete_id,
                workout_date,
                source,
                workout_name,
                description,
                sport_type,
                is_rest,
                total_duration_seconds,
                plan_payload,
                garmin_workout_id,
                garmin_schedule_status
            )
            VALUES (
                %(athlete_id)s,
                %(workout_date)s,
                %(source)s,
                %(workout_name)s,
                %(description)s,
                %(sport_type)s,
                %(is_rest)s,
                %(total_duration_seconds)s,
                %(plan_payload)s::jsonb,
                %(garmin_workout_id)s,
                %(garmin_schedule_status)s
            )
            ON CONFLICT (athlete_id, workout_date, source)
            DO UPDATE SET
                workout_name = EXCLUDED.workout_name,
                description = COALESCE(planned_workouts.description, EXCLUDED.description),
                total_duration_seconds = GREATEST(
                    planned_workouts.total_duration_seconds,
                    EXCLUDED.total_duration_seconds
                ),
                garmin_workout_id = COALESCE(
                    planned_workouts.garmin_workout_id,
                    EXCLUDED.garmin_workout_id
                ),
                garmin_schedule_status = COALESCE(
                    planned_workouts.garmin_schedule_status,
                    EXCLUDED.garmin_schedule_status
                )
        """
        for item in scheduled_items:
            workout_date_raw = item.get("date")
            if not workout_date_raw:
                continue
            workout_name = str(item.get("title") or "").strip()
            workout_date = date.fromisoformat(str(workout_date_raw))
            duration_seconds = self._calendar_duration_seconds(item)
            is_rest = "rest" in workout_name.lower()
            self._execute(
                query,
                {
                    "athlete_id": athlete_id,
                    "workout_date": workout_date,
                    "source": WORKOUT_SOURCE,
                    "workout_name": workout_name,
                    "description": "Garmin 캘린더에서 백필된 과거 워크아웃입니다.",
                    "sport_type": "RUNNING",
                    "is_rest": is_rest,
                    "total_duration_seconds": duration_seconds,
                    "plan_payload": json.dumps({"calendarItem": item}, ensure_ascii=False),
                    "garmin_workout_id": (
                        str(item.get("workoutId")) if item.get("workoutId") else None
                    ),
                    "garmin_schedule_status": "scheduled_backfill",
                },
            )
            inserted += 1
        return inserted

    def record_activities(self, activities: list[dict[str, Any]]) -> None:
        """Garmin 활동/랩 이력 저장."""
        athlete_id = self._athlete_id()
        for activity in activities:
            summary = cast(dict[str, Any], activity.get("summary", {}))
            details = cast(dict[str, Any], activity.get("details", {}))
            splits = cast(list[dict[str, Any]], activity.get("splits", []))

            started_at = self._extract_started_at(summary)
            distance_km = self._meters_to_km(
                summary.get("distance")
                or details.get("distance")
                or details.get("summaryDTO", {}).get("distance")
            )
            duration_seconds = self._duration_seconds(summary, details)
            avg_hr = self._int_or_none(
                summary.get("averageHR") or details.get("summaryDTO", {}).get("averageHR")
            )
            max_hr = self._int_or_none(
                summary.get("maxHR") or details.get("summaryDTO", {}).get("maxHR")
            )
            calories = self._int_or_none(
                summary.get("calories") or details.get("summaryDTO", {}).get("calories")
            )
            elevation_gain_m = self._float_or_none(
                summary.get("elevationGain") or details.get("summaryDTO", {}).get("elevationGain")
            )

            activity_row = self._fetchone(
                """
                INSERT INTO activities (
                    athlete_id,
                    garmin_activity_id,
                    activity_date,
                    started_at,
                    name,
                    sport_type,
                    distance_km,
                    duration_seconds,
                    avg_pace,
                    avg_hr,
                    max_hr,
                    elevation_gain_m,
                    calories,
                    raw_payload
                )
                VALUES (
                    %(athlete_id)s,
                    %(garmin_activity_id)s,
                    %(activity_date)s,
                    %(started_at)s,
                    %(name)s,
                    %(sport_type)s,
                    %(distance_km)s,
                    %(duration_seconds)s,
                    %(avg_pace)s,
                    %(avg_hr)s,
                    %(max_hr)s,
                    %(elevation_gain_m)s,
                    %(calories)s,
                    %(raw_payload)s::jsonb
                )
                ON CONFLICT (athlete_id, garmin_activity_id)
                DO UPDATE SET
                    activity_date = EXCLUDED.activity_date,
                    started_at = EXCLUDED.started_at,
                    name = EXCLUDED.name,
                    sport_type = EXCLUDED.sport_type,
                    distance_km = EXCLUDED.distance_km,
                    duration_seconds = EXCLUDED.duration_seconds,
                    avg_pace = EXCLUDED.avg_pace,
                    avg_hr = EXCLUDED.avg_hr,
                    max_hr = EXCLUDED.max_hr,
                    elevation_gain_m = EXCLUDED.elevation_gain_m,
                    calories = EXCLUDED.calories,
                    raw_payload = EXCLUDED.raw_payload
                RETURNING activity_id, activity_date, distance_km, duration_seconds
                """,
                {
                    "athlete_id": athlete_id,
                    "garmin_activity_id": summary.get("activityId"),
                    "activity_date": (
                        started_at.date() if started_at is not None else date.today()
                    ),
                    "started_at": started_at,
                    "name": summary.get("activityName"),
                    "sport_type": self._sport_type(summary),
                    "distance_km": distance_km,
                    "duration_seconds": duration_seconds,
                    "avg_pace": self._avg_pace(summary, details),
                    "avg_hr": avg_hr,
                    "max_hr": max_hr,
                    "elevation_gain_m": elevation_gain_m,
                    "calories": calories,
                    "raw_payload": json.dumps(
                        {"summary": summary, "details": details}, ensure_ascii=False
                    ),
                },
            )
            if activity_row is None:
                continue

            activity_id = str(activity_row["activity_id"])
            self._execute(
                "DELETE FROM activity_laps WHERE activity_id = %(activity_id)s",
                {"activity_id": activity_id},
            )
            for lap_index, split in enumerate(splits, start=1):
                self._execute(
                    """
                    INSERT INTO activity_laps (
                        activity_id,
                        lap_index,
                        distance_km,
                        duration_seconds,
                        avg_pace,
                        avg_hr,
                        raw_payload
                    )
                    VALUES (
                        %(activity_id)s,
                        %(lap_index)s,
                        %(distance_km)s,
                        %(duration_seconds)s,
                        %(avg_pace)s,
                        %(avg_hr)s,
                        %(raw_payload)s::jsonb
                    )
                    """,
                    {
                        "activity_id": activity_id,
                        "lap_index": lap_index,
                        "distance_km": self._meters_to_km(
                            split.get("distance") or split.get("totalDistanceInMeters")
                        ),
                        "duration_seconds": self._int_or_none(
                            split.get("duration") or split.get("totalTimeInSeconds")
                        ),
                        "avg_pace": self._pace_from_split(split),
                        "avg_hr": self._int_or_none(split.get("averageHR")),
                        "raw_payload": json.dumps(split, ensure_ascii=False),
                    },
                )

            if self._is_running_sport_type(summary):
                self._upsert_workout_execution(
                    athlete_id=athlete_id,
                    activity_id=activity_id,
                    activity_date=activity_row["activity_date"],
                    distance_km=self._float_or_none(activity_row["distance_km"]),
                    duration_seconds=self._int_or_none(activity_row["duration_seconds"]),
                )

    def rebuild_recent_workout_executions(self, as_of: date, days: int = 84) -> int:
        """최근 러닝 활동 execution을 다시 계산."""
        athlete_id = self._athlete_id()
        cutoff = as_of - timedelta(days=days - 1)
        self._execute(
            """
            DELETE FROM workout_executions
            WHERE athlete_id = %(athlete_id)s
              AND execution_date BETWEEN %(cutoff)s AND %(as_of)s
            """,
            {"athlete_id": athlete_id, "cutoff": cutoff, "as_of": as_of},
        )
        rows = self._fetchall(
            """
            SELECT activity_id, activity_date, distance_km, duration_seconds
            FROM activities
            WHERE athlete_id = %(athlete_id)s
              AND activity_date BETWEEN %(cutoff)s AND %(as_of)s
              AND sport_type IN ('running', 'treadmill_running', 'trail_running')
            ORDER BY activity_date
            """,
            {"athlete_id": athlete_id, "cutoff": cutoff, "as_of": as_of},
        )
        for row in rows:
            self._upsert_workout_execution(
                athlete_id=athlete_id,
                activity_id=str(row["activity_id"]),
                activity_date=row["activity_date"],
                distance_km=self._float_or_none(row["distance_km"]),
                duration_seconds=self._int_or_none(row["duration_seconds"]),
            )
        return len(rows)

    def record_coach_decision(
        self,
        decision_date: date,
        summary: str,
        metrics: AdvancedMetrics,
        plan: TrainingPlan,
        training_background: Optional[dict[str, Any]] = None,
    ) -> None:
        """코치 의사결정 요약 저장."""
        rationale = {
            "health": metrics.health.to_dict(),
            "performance": metrics.performance.to_dict(),
            "context": metrics.context.to_dict(),
            "plannedWorkouts": [self._serialize_daily_plan(day) for day in plan.plan],
        }
        state_snapshot = self.summarize_coaching_state(decision_date)
        rationale["coachingState"] = state_snapshot
        if training_background:
            rationale["trainingBackground"] = training_background
        query = """
            INSERT INTO coach_decisions (
                athlete_id,
                decision_date,
                decision_type,
                readiness_score,
                fatigue_score,
                injury_risk_score,
                decision_summary,
                rationale
            )
            VALUES (
                %(athlete_id)s,
                %(decision_date)s,
                'daily_plan',
                %(readiness_score)s,
                %(fatigue_score)s,
                %(injury_risk_score)s,
                %(decision_summary)s,
                %(rationale)s::jsonb
            )
        """
        self._execute(
            query,
            {
                "athlete_id": self._athlete_id(),
                "decision_date": decision_date,
                "readiness_score": state_snapshot["readinessScore"],
                "fatigue_score": state_snapshot["fatigueScore"],
                "injury_risk_score": state_snapshot["injuryRiskScore"],
                "decision_summary": summary,
                "rationale": json.dumps(rationale, ensure_ascii=False),
            },
        )

    def summarize_training_background(self, as_of: date) -> dict[str, Any]:
        """최근 6주/12개월/평생 훈련 배경 요약."""
        athlete_id = self._athlete_id()
        weekly_rows = self._fetchall(
            """
            SELECT
                date_trunc('week', activity_date)::date AS week_start,
                ROUND(COALESCE(SUM(distance_km), 0)::numeric, 2) AS distance_km,
                COUNT(*) AS run_count,
                MAX(distance_km) AS long_run_km
            FROM activities
            WHERE athlete_id = %(athlete_id)s
              AND activity_date >= %(cutoff)s
              AND sport_type IN ('running', 'treadmill_running', 'trail_running')
            GROUP BY 1
            ORDER BY 1 DESC
            LIMIT 6
            """,
            {"athlete_id": athlete_id, "cutoff": as_of - timedelta(days=42)},
        )
        monthly_rows = self._fetchall(
            """
            SELECT
                date_trunc('month', activity_date)::date AS month_start,
                ROUND(COALESCE(SUM(distance_km), 0)::numeric, 2) AS distance_km,
                COUNT(*) AS run_count
            FROM activities
            WHERE athlete_id = %(athlete_id)s
              AND activity_date >= %(cutoff)s
              AND sport_type IN ('running', 'treadmill_running', 'trail_running')
            GROUP BY 1
            ORDER BY 1 DESC
            LIMIT 12
            """,
            {"athlete_id": athlete_id, "cutoff": as_of - timedelta(days=365)},
        )
        lifetime_row = self._fetchone(
            """
            SELECT
                COUNT(*) AS total_run_count,
                ROUND(COALESCE(SUM(distance_km), 0)::numeric, 2) AS total_distance_km,
                ROUND(COALESCE(MAX(distance_km), 0)::numeric, 2) AS longest_run_km,
                MIN(activity_date) AS first_run_date
            FROM activities
            WHERE athlete_id = %(athlete_id)s
              AND sport_type IN ('running', 'treadmill_running', 'trail_running')
            """,
            {"athlete_id": athlete_id},
        ) or {}

        return {
            "recent6Weeks": [
                {
                    "weekStart": row["week_start"].isoformat(),
                    "distanceKm": float(row["distance_km"] or 0.0),
                    "runCount": int(row["run_count"] or 0),
                    "longRunKm": float(row["long_run_km"] or 0.0),
                }
                for row in weekly_rows
            ],
            "recent12Months": [
                {
                    "monthStart": row["month_start"].isoformat(),
                    "distanceKm": float(row["distance_km"] or 0.0),
                    "runCount": int(row["run_count"] or 0),
                }
                for row in monthly_rows
            ],
            "lifetime": {
                "totalRunCount": int(lifetime_row.get("total_run_count") or 0),
                "totalDistanceKm": float(lifetime_row.get("total_distance_km") or 0.0),
                "longestRunKm": float(lifetime_row.get("longest_run_km") or 0.0),
                "firstRunDate": (
                    lifetime_row["first_run_date"].isoformat()
                    if lifetime_row.get("first_run_date") is not None
                    else None
                ),
            },
            "coachingState": self.summarize_coaching_state(as_of),
            "planningConstraints": self.summarize_planning_constraints(as_of),
        }

    def list_recent_completed_activities(
        self,
        as_of: date,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        """캘린더 표출용 최근 실제 활동 목록."""
        athlete_id = self._athlete_id()
        rows = self._fetchall(
            """
            SELECT
                a.garmin_activity_id,
                a.activity_date,
                a.started_at,
                a.name,
                a.sport_type,
                a.distance_km,
                a.duration_seconds,
                a.avg_pace,
                a.avg_hr,
                a.max_hr,
                a.elevation_gain_m,
                we.target_match_score,
                we.execution_payload->>'plannedCategory' AS planned_category,
                we.execution_payload->>'actualCategory' AS actual_category,
                we.execution_payload->>'executionStatus' AS execution_status,
                pw.workout_name AS planned_workout_name
            FROM activities a
            LEFT JOIN workout_executions we
              ON we.activity_id = a.activity_id
            LEFT JOIN planned_workouts pw
              ON pw.planned_workout_id = we.planned_workout_id
            WHERE a.athlete_id = %(athlete_id)s
              AND a.activity_date BETWEEN %(from_date)s AND %(to_date)s
              AND a.sport_type IS NOT NULL
            ORDER BY a.activity_date DESC, a.started_at DESC NULLS LAST
            """,
            {
                "athlete_id": athlete_id,
                "from_date": as_of - timedelta(days=days - 1),
                "to_date": as_of,
            },
        )
        return [
            {
                "garminActivityId": row.get("garmin_activity_id"),
                "activityDate": row["activity_date"].isoformat(),
                "startedAt": (
                    row["started_at"].astimezone(ZoneInfo(TIMEZONE)).isoformat()
                    if row.get("started_at") is not None
                    else None
                ),
                "title": row.get("name") or self._display_sport_name(row.get("sport_type")),
                "sportType": self._display_sport_name(row.get("sport_type")),
                "distanceKm": self._float_or_none(row.get("distance_km")),
                "durationSeconds": self._int_or_none(row.get("duration_seconds")),
                "avgPace": row.get("avg_pace"),
                "avgHr": self._int_or_none(row.get("avg_hr")),
                "maxHr": self._int_or_none(row.get("max_hr")),
                "elevationGainM": self._float_or_none(row.get("elevation_gain_m")),
                "plannedWorkoutName": row.get("planned_workout_name"),
                "plannedCategory": row.get("planned_category"),
                "actualCategory": row.get("actual_category"),
                "executionStatus": row.get("execution_status"),
                "targetMatchScore": self._float_or_none(row.get("target_match_score")),
                "notes": self._actual_activity_note(row),
            }
            for row in rows
        ]

    def summarize_planning_constraints(self, as_of: date) -> dict[str, Any]:
        """가용시간/레이스/블록 제약 요약."""
        athlete_id = self._athlete_id()
        availability_rows = self._fetchall(
            """
            SELECT weekday, is_available, max_duration_minutes, preferred_session_type
            FROM availability_rules
            WHERE athlete_id = %(athlete_id)s
            ORDER BY weekday
            """,
            {"athlete_id": athlete_id},
        )
        goal_row = self._fetchone(
            """
            SELECT goal_name, race_date, distance, goal_time, target_pace, priority
            FROM race_goals
            WHERE athlete_id = %(athlete_id)s
              AND is_active = TRUE
              AND (race_date IS NULL OR race_date >= %(as_of)s)
            ORDER BY priority ASC, race_date ASC NULLS LAST
            LIMIT 1
            """,
            {"athlete_id": athlete_id, "as_of": as_of},
        ) or {}
        block_row = self._fetchone(
            """
            SELECT phase, starts_on, ends_on, focus, weekly_volume_target_km
            FROM training_blocks
            WHERE athlete_id = %(athlete_id)s
              AND starts_on <= %(as_of)s
              AND ends_on >= %(as_of)s
            ORDER BY starts_on DESC
            LIMIT 1
            """,
            {"athlete_id": athlete_id, "as_of": as_of},
        ) or {}
        return {
            "availability": [
                {
                    "weekday": int(row["weekday"]),
                    "isAvailable": bool(row["is_available"]),
                    "maxDurationMinutes": self._int_or_none(row.get("max_duration_minutes")),
                    "preferredSessionType": row.get("preferred_session_type"),
                }
                for row in availability_rows
            ],
            "raceGoal": {
                "goalName": goal_row.get("goal_name"),
                "raceDate": (
                    goal_row["race_date"].isoformat()
                    if goal_row.get("race_date") is not None
                    else None
                ),
                "distance": goal_row.get("distance"),
                "goalTime": goal_row.get("goal_time"),
                "targetPace": goal_row.get("target_pace"),
                "priority": self._int_or_none(goal_row.get("priority")),
            },
            "trainingBlock": {
                "phase": block_row.get("phase"),
                "startsOn": (
                    block_row["starts_on"].isoformat()
                    if block_row.get("starts_on") is not None
                    else None
                ),
                "endsOn": (
                    block_row["ends_on"].isoformat()
                    if block_row.get("ends_on") is not None
                    else None
                ),
                "focus": block_row.get("focus"),
                "weeklyVolumeTargetKm": self._float_or_none(
                    block_row.get("weekly_volume_target_km")
                ),
            },
        }

    def summarize_coaching_state(self, as_of: date) -> dict[str, Any]:
        """최근 수행/주관 피드백/부상 상태를 반영한 코칭 상태 요약."""
        athlete_id = self._athlete_id()
        adherence_window_days = 42
        load_row = self._fetchone(
            """
            SELECT
                ROUND(COALESCE(SUM(CASE
                    WHEN activity_date >= %(d7)s THEN distance_km ELSE 0
                END), 0)::numeric, 2) AS last_7d_distance_km,
                ROUND(COALESCE(SUM(CASE
                    WHEN activity_date >= %(d28)s THEN distance_km ELSE 0
                END), 0)::numeric, 2) AS last_28d_distance_km,
                COUNT(*) FILTER (WHERE activity_date >= %(d7)s) AS last_7d_run_count,
                MAX(activity_date) FILTER (
                    WHERE activity_date >= %(d21)s AND distance_km >= 15
                ) AS last_long_run_date,
                MAX(activity_date) FILTER (
                    WHERE activity_date >= %(d14)s
                      AND (
                        UPPER(COALESCE(raw_payload->'summary'->>'trainingEffectLabel', '')) IN
                            ('THRESHOLD', 'VO2_MAX', 'ANAEROBIC', 'TEMPO')
                        OR UPPER(COALESCE(name, '')) LIKE '%%INTERVAL%%'
                        OR UPPER(COALESCE(name, '')) LIKE '%%TEMPO%%'
                      )
                ) AS last_quality_date
            FROM activities
            WHERE athlete_id = %(athlete_id)s
              AND activity_date >= %(d28)s
              AND sport_type IN ('running', 'treadmill_running', 'trail_running')
            """,
            {
                "athlete_id": athlete_id,
                "d7": as_of - timedelta(days=6),
                "d14": as_of - timedelta(days=13),
                "d21": as_of - timedelta(days=20),
                "d28": as_of - timedelta(days=27),
            },
        ) or {}
        load_variability_row = self._fetchone(
            """
            WITH day_series AS (
                SELECT generate_series(%(d7)s::date, %(as_of)s::date, interval '1 day')::date AS day
            ),
            daily_loads AS (
                SELECT
                    activity_date,
                    ROUND(
                        COALESCE(SUM(CASE
                            WHEN sport_type IN ('running', 'treadmill_running', 'trail_running')
                            THEN distance_km ELSE 0
                        END), 0)::numeric,
                        2
                    ) AS running_km,
                    ROUND(
                        COALESCE(SUM(CASE
                            WHEN sport_type NOT IN ('running', 'treadmill_running', 'trail_running')
                            THEN duration_seconds ELSE 0
                        END), 0)::numeric / 60,
                        2
                    ) AS cross_training_minutes,
                    ROUND(
                        (
                            COALESCE(SUM(CASE
                                WHEN sport_type IN ('running', 'treadmill_running', 'trail_running')
                                THEN distance_km ELSE 0
                            END), 0)
                            + COALESCE(
                                SUM(CASE
                                    WHEN sport_type NOT IN (
                                        'running',
                                        'treadmill_running',
                                        'trail_running'
                                    )
                                    THEN duration_seconds ELSE 0
                                END),
                                0
                            ) / 600.0
                        )::numeric,
                        2
                    ) AS load_units
                FROM activities
                WHERE athlete_id = %(athlete_id)s
                  AND activity_date BETWEEN %(d7)s AND %(as_of)s
                GROUP BY activity_date
            ),
            normalized_loads AS (
                SELECT
                    ds.day,
                    COALESCE(dl.running_km, 0) AS running_km,
                    COALESCE(dl.cross_training_minutes, 0) AS cross_training_minutes,
                    COALESCE(dl.load_units, 0) AS load_units
                FROM day_series ds
                LEFT JOIN daily_loads dl
                  ON dl.activity_date = ds.day
            )
            SELECT
                ROUND(AVG(load_units)::numeric, 2) AS avg_daily_load,
                ROUND(COALESCE(STDDEV_POP(load_units), 0)::numeric, 2) AS sd_daily_load,
                ROUND(SUM(load_units)::numeric, 2) AS total_load,
                ROUND(MAX(load_units)::numeric, 2) AS peak_daily_load,
                ROUND(SUM(cross_training_minutes)::numeric, 2) AS last_7d_cross_training_minutes,
                COUNT(*) FILTER (WHERE load_units > 0) AS active_days
            FROM normalized_loads
            """,
            {
                "athlete_id": athlete_id,
                "d7": as_of - timedelta(days=6),
                "as_of": as_of,
            },
        ) or {}
        daily_load_rows = self._fetchall(
            """
            WITH day_series AS (
                SELECT
                    generate_series(
                        %(d42)s::date,
                        %(as_of)s::date,
                        interval '1 day'
                    )::date AS day
            ),
            daily_loads AS (
                SELECT
                    activity_date,
                    ROUND(
                        (
                            COALESCE(SUM(CASE
                                WHEN sport_type IN ('running', 'treadmill_running', 'trail_running')
                                THEN distance_km ELSE 0
                            END), 0)
                            + COALESCE(
                                SUM(CASE
                                    WHEN sport_type NOT IN (
                                        'running',
                                        'treadmill_running',
                                        'trail_running'
                                    )
                                    THEN duration_seconds ELSE 0
                                END),
                                0
                            ) / 600.0
                        )::numeric,
                        2
                    ) AS load_units
                FROM activities
                WHERE athlete_id = %(athlete_id)s
                  AND activity_date BETWEEN %(d42)s AND %(as_of)s
                GROUP BY activity_date
            )
            SELECT
                ds.day,
                COALESCE(dl.load_units, 0) AS load_units
            FROM day_series ds
            LEFT JOIN daily_loads dl
              ON dl.activity_date = ds.day
            ORDER BY ds.day
            """,
            {
                "athlete_id": athlete_id,
                "d42": as_of - timedelta(days=41),
                "as_of": as_of,
            },
        )
        acute_ewma_load = self._ewma_load(daily_load_rows, span_days=7)
        chronic_ewma_load = self._ewma_load(daily_load_rows, span_days=28)
        ewma_load_ratio = self._ewma_ratio(acute_ewma_load, chronic_ewma_load)
        recovery_row = self._fetchone(
            """
            SELECT
                body_battery,
                hrv,
                sleep_score,
                training_status
            FROM daily_metrics
            WHERE athlete_id = %(athlete_id)s
              AND metric_date <= %(as_of)s
            ORDER BY metric_date DESC
            LIMIT 1
            """,
            {"athlete_id": athlete_id, "as_of": as_of},
        ) or {}
        adherence_row = self._fetchone(
            """
            WITH recent_plans AS (
                SELECT planned_workout_id, is_rest, workout_date
                FROM planned_workouts
                WHERE athlete_id = %(athlete_id)s
                  AND source = %(source)s
                  AND workout_date BETWEEN %(from_date)s AND %(to_date)s
            ),
            plan_window AS (
                SELECT MIN(workout_date) AS first_plan_date
                FROM recent_plans
                WHERE NOT is_rest
            ),
            plan_status AS (
                SELECT
                    rp.planned_workout_id,
                    rp.is_rest,
                    MAX(we.completion_ratio) AS completion_ratio,
                    MAX(we.target_match_score) AS target_match_score
                FROM recent_plans rp
                LEFT JOIN workout_executions we
                  ON we.planned_workout_id = rp.planned_workout_id
                GROUP BY rp.planned_workout_id, rp.is_rest
            ),
            unplanned AS (
                SELECT COUNT(*) AS count
                FROM workout_executions we
                CROSS JOIN plan_window pw
                WHERE we.athlete_id = %(athlete_id)s
                  AND we.execution_date BETWEEN %(from_date)s AND %(to_date)s
                  AND pw.first_plan_date IS NOT NULL
                  AND we.execution_date >= pw.first_plan_date
                  AND COALESCE(we.execution_payload->>'plannedCategory', 'unplanned') = 'unplanned'
            )
            SELECT
                COUNT(*) FILTER (WHERE NOT is_rest) AS planned_workout_count,
                COUNT(*) FILTER (
                    WHERE NOT is_rest
                      AND completion_ratio IS NOT NULL
                      AND target_match_score >= %(meaningful_match_threshold)s
                ) AS matched_workout_count,
                COUNT(*) FILTER (
                    WHERE NOT is_rest
                      AND (
                        completion_ratio IS NULL
                        OR target_match_score < %(meaningful_match_threshold)s
                      )
                ) AS skipped_workout_count,
                ROUND(AVG(completion_ratio) FILTER (
                    WHERE target_match_score >= %(meaningful_match_threshold)s
                )::numeric, 2) AS avg_completion_ratio,
                ROUND(AVG(target_match_score) FILTER (
                    WHERE target_match_score >= %(meaningful_match_threshold)s
                )::numeric, 2) AS avg_target_match_score,
                (SELECT count FROM unplanned) AS unplanned_run_count
            FROM plan_status
            """,
            {
                "athlete_id": athlete_id,
                "source": WORKOUT_SOURCE,
                "from_date": as_of - timedelta(days=adherence_window_days - 1),
                "to_date": as_of,
                "meaningful_match_threshold": MEANINGFUL_MATCH_THRESHOLD,
            },
        ) or {}
        feedback_row = self._fetchone(
            """
            SELECT
                feedback_date,
                fatigue_score,
                soreness_score,
                stress_score,
                motivation_score,
                sleep_quality_score,
                pain_notes,
                notes
            FROM subjective_feedback
            WHERE athlete_id = %(athlete_id)s
              AND feedback_date <= %(as_of)s
            ORDER BY feedback_date DESC
            LIMIT 1
            """,
            {"athlete_id": athlete_id, "as_of": as_of},
        ) or {}
        injury_row = self._fetchone(
            """
            SELECT
                injury_area,
                severity,
                status_date,
                notes
            FROM injury_status
            WHERE athlete_id = %(athlete_id)s
              AND is_active = TRUE
              AND status_date <= %(as_of)s
            ORDER BY severity DESC, status_date DESC
            LIMIT 1
            """,
            {"athlete_id": athlete_id, "as_of": as_of},
        ) or {}

        readiness_score = self._readiness_score_from_history(
            load_row,
            load_variability_row,
            acute_ewma_load,
            chronic_ewma_load,
            ewma_load_ratio,
            recovery_row,
            adherence_row,
            feedback_row,
        )
        fatigue_score = self._fatigue_score_from_history(
            load_row,
            load_variability_row,
            acute_ewma_load,
            chronic_ewma_load,
            ewma_load_ratio,
            recovery_row,
            feedback_row,
        )
        injury_risk_score = self._injury_risk_score_from_history(
            load_row,
            load_variability_row,
            acute_ewma_load,
            chronic_ewma_load,
            ewma_load_ratio,
            recovery_row,
            feedback_row,
            injury_row,
        )
        monotony = CoachingHistoryService._training_monotony(load_variability_row)
        strain = CoachingHistoryService._training_strain(load_variability_row)

        return {
            "readinessScore": readiness_score,
            "fatigueScore": fatigue_score,
            "injuryRiskScore": injury_risk_score,
            "adherenceWindowDays": adherence_window_days,
            "meaningfulMatchThreshold": MEANINGFUL_MATCH_THRESHOLD,
            "historyConfidence": self._adherence_history_confidence(
                adherence_row.get("planned_workout_count")
            ),
            "load": {
                "last7dDistanceKm": float(load_row.get("last_7d_distance_km") or 0.0),
                "last28dDistanceKm": float(load_row.get("last_28d_distance_km") or 0.0),
                "last7dRunCount": int(load_row.get("last_7d_run_count") or 0),
                "last7dCrossTrainingMinutes": float(
                    load_variability_row.get("last_7d_cross_training_minutes") or 0.0
                ),
                "avgDailyLoad": float(load_variability_row.get("avg_daily_load") or 0.0),
                "peakDailyLoad": float(load_variability_row.get("peak_daily_load") or 0.0),
                "activeDays": int(load_variability_row.get("active_days") or 0),
                "acuteEwmaLoad": acute_ewma_load,
                "chronicEwmaLoad": chronic_ewma_load,
                "ewmaLoadRatio": ewma_load_ratio,
                "trainingMonotony": monotony,
                "trainingStrain": strain,
                "daysSinceLongRun": self._days_since(as_of, load_row.get("last_long_run_date")),
                "daysSinceQuality": self._days_since(as_of, load_row.get("last_quality_date")),
            },
            "recovery": {
                "bodyBattery": self._int_or_none(recovery_row.get("body_battery")),
                "hrv": self._int_or_none(recovery_row.get("hrv")),
                "sleepScore": self._int_or_none(recovery_row.get("sleep_score")),
                "trainingStatus": recovery_row.get("training_status"),
            },
            "adherence": {
                "plannedWorkoutCount": int(adherence_row.get("planned_workout_count") or 0),
                "matchedWorkoutCount": int(adherence_row.get("matched_workout_count") or 0),
                "skippedWorkoutCount": int(adherence_row.get("skipped_workout_count") or 0),
                "executionRate": self._completion_rate(
                    adherence_row.get("matched_workout_count"),
                    adherence_row.get("planned_workout_count"),
                ),
                "avgCompletionRatio": self._float_or_none(
                    adherence_row.get("avg_completion_ratio")
                ),
                "avgTargetMatchScore": self._float_or_none(
                    adherence_row.get("avg_target_match_score")
                ),
                "unplannedRunCount": int(adherence_row.get("unplanned_run_count") or 0),
            },
            "subjectiveFeedback": self._serialize_feedback(feedback_row),
            "activeInjury": {
                "injuryArea": injury_row.get("injury_area"),
                "severity": self._int_or_none(injury_row.get("severity")),
                "statusDate": (
                    injury_row["status_date"].isoformat()
                    if injury_row.get("status_date") is not None
                    else None
                ),
                "notes": injury_row.get("notes"),
            },
        }

    def _athlete_id(self) -> str:
        query = "SELECT athlete_id FROM athletes WHERE external_key = %(external_key)s"
        rows = self._fetchall(query, {"external_key": self.athlete_key})
        if not rows:
            raise ValueError("Athlete must be created before writing history")
        return str(rows[0]["athlete_id"])

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

    def _upsert_workout_execution(
        self,
        athlete_id: str,
        activity_id: str,
        activity_date: date,
        distance_km: Optional[float],
        duration_seconds: Optional[int],
    ) -> None:
        actual_category = self._actual_activity_category(activity_id)
        planned = self._select_best_planned_workout(
            athlete_id=athlete_id,
            activity_date=activity_date,
            actual_category=actual_category,
            actual_duration=duration_seconds,
        )
        planned_workout_id = planned["planned_workout_id"] if planned else None
        target_duration = self._int_or_none(planned["total_duration_seconds"] if planned else None)
        completion_ratio = None
        if duration_seconds and target_duration and target_duration > 0:
            completion_ratio = round(duration_seconds / target_duration, 2)
        planned_category = self._planned_workout_category(planned)
        target_match_score = self._target_match_score(
            planned_category=planned_category,
            actual_category=actual_category,
            target_duration=target_duration,
            actual_duration=duration_seconds,
        )
        execution_status = self._execution_status(
            planned_category=planned_category,
            actual_category=actual_category,
            completion_ratio=completion_ratio,
            target_match_score=target_match_score,
        )
        date_offset_days = self._planned_workout_offset_days(activity_date, planned)

        self._execute(
            """
            DELETE FROM workout_executions
            WHERE athlete_id = %(athlete_id)s
              AND activity_id = %(activity_id)s
            """,
            {"athlete_id": athlete_id, "activity_id": activity_id},
        )

        query = """
            INSERT INTO workout_executions (
                athlete_id,
                planned_workout_id,
                activity_id,
                execution_date,
                completion_ratio,
                target_match_score,
                execution_payload
            )
            VALUES (
                %(athlete_id)s,
                %(planned_workout_id)s,
                %(activity_id)s,
                %(execution_date)s,
                %(completion_ratio)s,
                %(target_match_score)s,
                %(execution_payload)s::jsonb
            )
            ON CONFLICT DO NOTHING
        """
        self._execute(
            query,
            {
                "athlete_id": athlete_id,
                "planned_workout_id": planned_workout_id,
                "activity_id": activity_id,
                "execution_date": activity_date,
                "completion_ratio": completion_ratio,
                "target_match_score": target_match_score,
                "execution_payload": json.dumps(
                    {
                        "distanceKm": distance_km,
                        "durationSeconds": duration_seconds,
                        "plannedCategory": planned_category,
                        "actualCategory": actual_category,
                        "executionStatus": execution_status,
                        "matchedPlannedDate": (
                            planned["workout_date"].isoformat()
                            if planned and planned.get("workout_date") is not None
                            else None
                        ),
                        "dateOffsetDays": date_offset_days,
                        "matchingStrategy": "category_duration_date",
                    }
                ),
            },
        )

    def _select_best_planned_workout(
        self,
        athlete_id: str,
        activity_date: date,
        actual_category: str,
        actual_duration: Optional[int],
    ) -> Optional[dict[str, Any]]:
        candidates = self._fetchall(
            """
            SELECT
                pw.planned_workout_id,
                pw.total_duration_seconds,
                pw.workout_name,
                pw.plan_payload,
                pw.workout_date,
                EXISTS (
                    SELECT 1
                    FROM workout_executions we
                    WHERE we.planned_workout_id = pw.planned_workout_id
                ) AS already_matched
            FROM planned_workouts pw
            WHERE athlete_id = %(athlete_id)s
              AND source = %(source)s
              AND workout_date BETWEEN %(date_from)s AND %(date_to)s
            """,
            {
                "athlete_id": athlete_id,
                "date_from": activity_date - timedelta(days=1),
                "date_to": activity_date + timedelta(days=2),
                "source": WORKOUT_SOURCE,
            },
        )
        if not candidates:
            return None

        scored = sorted(
            candidates,
            key=lambda candidate: self._planned_match_score(
                activity_date=activity_date,
                candidate=candidate,
                actual_category=actual_category,
                actual_duration=actual_duration,
            ),
            reverse=True,
        )
        best = scored[0]
        score = self._planned_match_score(
            activity_date=activity_date,
            candidate=best,
            actual_category=actual_category,
            actual_duration=actual_duration,
        )
        return best if score >= PLANNED_MATCH_SELECTION_THRESHOLD else None

    @staticmethod
    def _serialize_daily_plan(day: DailyPlan) -> dict[str, Any]:
        return {
            "date": day.date.isoformat(),
            "workout": day.workout.model_dump(by_alias=True),
        }

    @staticmethod
    def _extract_started_at(summary: dict[str, Any]) -> Optional[datetime]:
        raw = summary.get("startTimeLocal")
        if not isinstance(raw, str):
            return None
        normalized = raw.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=ZoneInfo(TIMEZONE))
            return parsed
        except ValueError:
            return None

    @staticmethod
    def _sport_type(summary: dict[str, Any]) -> Optional[str]:
        activity_type = summary.get("activityType")
        if isinstance(activity_type, dict):
            return cast(Optional[str], activity_type.get("typeKey"))
        return None

    @staticmethod
    def _display_sport_name(value: Any) -> str:
        sport_type = str(value or "workout").lower()
        labels = {
            "running": "러닝",
            "treadmill_running": "트레드밀 러닝",
            "trail_running": "트레일 러닝",
            "cycling": "사이클링",
            "hiking": "등산",
            "strength_training": "근력 운동",
            "walking": "걷기",
        }
        return labels.get(sport_type, sport_type.replace("_", " ").title())

    @staticmethod
    def _actual_activity_note(row: dict[str, Any]) -> str:
        planned_name = row.get("planned_workout_name")
        planned_category = row.get("planned_category")
        actual_category = row.get("actual_category")
        execution_status = row.get("execution_status") or "completed_unplanned"
        target_match_score = CoachingHistoryService._float_or_none(row.get("target_match_score"))
        status_label = CoachingHistoryService._execution_status_label(execution_status)
        if planned_name:
            score_label = (
                f"{int(target_match_score * 100)}점"
                if target_match_score is not None
                else "평가 없음"
            )
            return (
                "Garmin 실제 수행 기록\n"
                f"상태: {status_label}\n"
                f"계획: {planned_name}\n"
                f"계획 유형: {planned_category or '-'}\n"
                f"실제 유형: {actual_category or '-'}\n"
                f"매칭 점수: {score_label}"
            )
        return f"Garmin 실제 수행 기록\n상태: {status_label}\n계획 대비: 계획 없음"

    @staticmethod
    def _execution_status(
        planned_category: str,
        actual_category: str,
        completion_ratio: Optional[float],
        target_match_score: Optional[float],
    ) -> str:
        if planned_category == "unplanned":
            return "completed_unplanned"
        if target_match_score is not None and target_match_score >= 0.8:
            return "completed_as_planned"
        if planned_category != actual_category:
            return "completed_substituted"
        if completion_ratio is not None and completion_ratio < 0.75:
            return "completed_partial"
        return "completed_partial"

    @staticmethod
    def _execution_status_label(value: Any) -> str:
        labels = {
            "completed_as_planned": "수행 완료",
            "completed_partial": "부분 수행",
            "completed_substituted": "대체 수행",
            "completed_unplanned": "비계획 수행",
        }
        return labels.get(str(value or ""), "실제 수행")

    @staticmethod
    def _is_running_sport_type(summary: dict[str, Any]) -> bool:
        sport_type = CoachingHistoryService._sport_type(summary)
        return sport_type in RUNNING_SPORT_TYPES

    @staticmethod
    def _duration_seconds(summary: dict[str, Any], details: dict[str, Any]) -> Optional[int]:
        raw = (
            summary.get("duration")
            or details.get("summaryDTO", {}).get("duration")
            or details.get("summaryDTO", {}).get("movingDuration")
        )
        return CoachingHistoryService._int_or_none(raw)

    @staticmethod
    def _avg_pace(summary: dict[str, Any], details: dict[str, Any]) -> Optional[str]:
        distance_m = summary.get("distance") or details.get("summaryDTO", {}).get("distance")
        duration_s = CoachingHistoryService._duration_seconds(summary, details)
        if not distance_m or not duration_s:
            return None
        seconds_per_km = int(duration_s / (float(distance_m) / 1000))
        minutes = seconds_per_km // 60
        seconds = seconds_per_km % 60
        return f"{minutes}:{seconds:02d}"

    @staticmethod
    def _pace_from_split(split: dict[str, Any]) -> Optional[str]:
        duration = CoachingHistoryService._int_or_none(
            split.get("duration") or split.get("totalTimeInSeconds")
        )
        distance_km = CoachingHistoryService._meters_to_km(
            split.get("distance") or split.get("totalDistanceInMeters")
        )
        if not duration or not distance_km or distance_km <= 0:
            return None
        seconds_per_km = int(duration / distance_km)
        minutes = seconds_per_km // 60
        seconds = seconds_per_km % 60
        return f"{minutes}:{seconds:02d}"

    @staticmethod
    def _meters_to_km(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return round(float(value) / 1000, 2)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _calendar_duration_seconds(item: dict[str, Any]) -> int:
        raw = item.get("elapsedDuration") or item.get("duration")
        try:
            return int(raw or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _int_or_none(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _float_or_none(value: Any) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _planned_workout_category(planned: Optional[dict[str, Any]]) -> str:
        if not planned:
            return "unplanned"
        workout_name = str(planned.get("workout_name") or "").lower()
        plan_payload = cast(dict[str, Any], planned.get("plan_payload") or {})
        workout = cast(dict[str, Any], plan_payload.get("workout") or {})
        steps = cast(list[dict[str, Any]], workout.get("steps") or [])
        step_types = {str(step.get("type", "")).lower() for step in steps}

        if "long" in workout_name:
            return "long_run"
        if any(keyword in workout_name for keyword in ("interval", "threshold", "tempo", "vo2")):
            return "quality"
        if "recovery" in workout_name:
            return "recovery"
        if any(step_type in {"interval", "recovery"} for step_type in step_types):
            return "quality"
        if "rest" in workout_name:
            return "rest"
        return "base"

    def _actual_activity_category(self, activity_id: str) -> str:
        row = self._fetchone(
            """
            SELECT name, distance_km, duration_seconds, avg_hr, raw_payload
            FROM activities
            WHERE activity_id = %(activity_id)s
            """,
            {"activity_id": activity_id},
        )
        if not row:
            return "unknown"
        raw_payload = cast(dict[str, Any], row.get("raw_payload") or {})
        summary = cast(dict[str, Any], raw_payload.get("summary") or {})
        details = cast(dict[str, Any], raw_payload.get("details") or {})
        label = str(summary.get("trainingEffectLabel") or "").upper()
        avg_hr = self._int_or_none(row.get("avg_hr"))
        duration_seconds = self._int_or_none(row.get("duration_seconds"))
        distance_km = self._float_or_none(row.get("distance_km"))

        if label in {"THRESHOLD", "VO2_MAX", "ANAEROBIC", "TEMPO"}:
            return "quality"
        if distance_km and distance_km >= 15:
            return "long_run"
        if duration_seconds and duration_seconds >= 75 * 60:
            return "long_run"
        if avg_hr and self._looks_easy_run(avg_hr):
            return "recovery"

        splits = cast(list[dict[str, Any]], details.get("lapDTOs") or [])
        if any(str(split.get("intensityType") or "").upper() == "INTERVAL" for split in splits[1:]):
            return "quality"
        return "base"

    @staticmethod
    def _target_match_score(
        planned_category: str,
        actual_category: str,
        target_duration: Optional[int],
        actual_duration: Optional[int],
    ) -> Optional[float]:
        if target_duration is None and actual_duration is None:
            return None
        duration_score = 0.0
        if target_duration and actual_duration and target_duration > 0:
            duration_score = max(0.0, 1 - abs(actual_duration - target_duration) / target_duration)
        type_score = 0.0
        if planned_category == actual_category:
            type_score = 1.0
        elif {planned_category, actual_category} <= {"recovery", "base"}:
            type_score = 0.7
        elif planned_category == "quality" and actual_category == "long_run":
            type_score = 0.2
        elif planned_category == "long_run" and actual_category == "base":
            type_score = 0.6
        return round((duration_score * 0.7) + (type_score * 0.3), 2)

    @staticmethod
    def _looks_easy_run(avg_hr: int) -> bool:
        return avg_hr < 150

    @staticmethod
    def _days_since(as_of: date, candidate: Any) -> Optional[int]:
        if not isinstance(candidate, date):
            return None
        return (as_of - candidate).days

    @staticmethod
    def _planned_workout_offset_days(
        activity_date: date, planned: Optional[dict[str, Any]]
    ) -> Optional[int]:
        if not planned or not isinstance(planned.get("workout_date"), date):
            return None
        return (activity_date - cast(date, planned["workout_date"])).days

    def _planned_match_score(
        self,
        activity_date: date,
        candidate: dict[str, Any],
        actual_category: str,
        actual_duration: Optional[int],
    ) -> float:
        planned_category = self._planned_workout_category(candidate)
        target_duration = self._int_or_none(candidate.get("total_duration_seconds"))
        target_match = self._target_match_score(
            planned_category=planned_category,
            actual_category=actual_category,
            target_duration=target_duration,
            actual_duration=actual_duration,
        ) or 0.0
        offset_days = self._planned_workout_offset_days(activity_date, candidate)
        date_score = 1.0 if offset_days == 0 else 0.8 if offset_days in {-1, 1} else 0.5
        duplication_penalty = 0.15 if candidate.get("already_matched") else 0.0
        return round((target_match * 0.75) + (date_score * 0.25) - duplication_penalty, 3)

    @staticmethod
    def _serialize_feedback(feedback_row: dict[str, Any]) -> dict[str, Any]:
        return {
            "feedbackDate": (
                feedback_row["feedback_date"].isoformat()
                if feedback_row.get("feedback_date") is not None
                else None
            ),
            "fatigueScore": CoachingHistoryService._int_or_none(feedback_row.get("fatigue_score")),
            "sorenessScore": CoachingHistoryService._int_or_none(
                feedback_row.get("soreness_score")
            ),
            "stressScore": CoachingHistoryService._int_or_none(feedback_row.get("stress_score")),
            "motivationScore": CoachingHistoryService._int_or_none(
                feedback_row.get("motivation_score")
            ),
            "sleepQualityScore": CoachingHistoryService._int_or_none(
                feedback_row.get("sleep_quality_score")
            ),
            "painNotes": feedback_row.get("pain_notes"),
            "notes": feedback_row.get("notes"),
        }

    @staticmethod
    def _readiness_score_from_history(
        load_row: dict[str, Any],
        load_variability_row: dict[str, Any],
        acute_ewma_load: float,
        chronic_ewma_load: float,
        ewma_load_ratio: float,
        recovery_row: dict[str, Any],
        adherence_row: dict[str, Any],
        feedback_row: dict[str, Any],
    ) -> float:
        history_confidence = CoachingHistoryService._adherence_history_confidence(
            adherence_row.get("planned_workout_count")
        )
        monotony = CoachingHistoryService._training_monotony(load_variability_row)
        strain = CoachingHistoryService._training_strain(load_variability_row)
        cross_training_minutes = float(
            load_variability_row.get("last_7d_cross_training_minutes") or 0.0
        )
        score = 60.0
        score -= float(load_row.get("last_7d_distance_km") or 0.0) * 0.22
        score += float(load_row.get("last_28d_distance_km") or 0.0) * 0.04
        score -= min(12.0, cross_training_minutes * 0.03)
        score -= max(0.0, monotony - 2.0) * 6.0
        score -= max(0.0, strain - 55.0) * 0.12
        score += min(6.0, chronic_ewma_load * 0.18)
        score -= max(0.0, ewma_load_ratio - 1.15) * 18.0
        score += max(0.0, 1.05 - abs(ewma_load_ratio - 1.0)) * 3.0
        score += (
            (float(adherence_row.get("avg_target_match_score") or 0.0) - 0.7)
            * 20
            * history_confidence
        )
        score += (
            CoachingHistoryService._completion_rate(
                adherence_row.get("matched_workout_count"),
                adherence_row.get("planned_workout_count"),
            )
            - 0.65
        ) * 25 * history_confidence
        score -= float(adherence_row.get("unplanned_run_count") or 0.0) * 2.5 * history_confidence
        score -= (
            float(adherence_row.get("skipped_workout_count") or 0.0) * 3.0 * history_confidence
        )
        score += (float(recovery_row.get("body_battery") or 50.0) - 50.0) * 0.35
        score += (float(recovery_row.get("sleep_score") or 70.0) - 70.0) * 0.12
        score += (float(recovery_row.get("hrv") or 60.0) - 60.0) * 0.08
        score -= float(feedback_row.get("fatigue_score") or 5) * 2.0
        score -= float(feedback_row.get("soreness_score") or 4) * 1.5
        score += float(feedback_row.get("motivation_score") or 5) * 1.5
        score += float(feedback_row.get("sleep_quality_score") or 5) * 1.0
        return float(round(max(0.0, min(score, 100.0)), 2))

    @staticmethod
    def _completion_rate(matched: Any, planned: Any) -> float:
        planned_count = CoachingHistoryService._int_or_none(planned) or 0
        matched_count = CoachingHistoryService._int_or_none(matched) or 0
        if planned_count <= 0:
            return 0.0
        return round(matched_count / planned_count, 2)

    @staticmethod
    def _adherence_history_confidence(planned: Any) -> float:
        planned_count = CoachingHistoryService._int_or_none(planned) or 0
        return round(min(planned_count / 4, 1.0), 2)

    @staticmethod
    def _fatigue_score_from_history(
        load_row: dict[str, Any],
        load_variability_row: dict[str, Any],
        acute_ewma_load: float,
        chronic_ewma_load: float,
        ewma_load_ratio: float,
        recovery_row: dict[str, Any],
        feedback_row: dict[str, Any],
    ) -> float:
        last_7d = float(load_row.get("last_7d_distance_km") or 0.0)
        last_28d = float(load_row.get("last_28d_distance_km") or 0.0)
        cross_training_minutes = float(
            load_variability_row.get("last_7d_cross_training_minutes") or 0.0
        )
        monotony = CoachingHistoryService._training_monotony(load_variability_row)
        strain = CoachingHistoryService._training_strain(load_variability_row)
        baseline_weekly = last_28d / 4 if last_28d > 0 else 0.0
        overload_ratio = (last_7d / baseline_weekly) if baseline_weekly > 0 else 1.0
        score = 20.0
        score += min(30.0, last_7d * 0.65)
        score += min(18.0, cross_training_minutes * 0.05)
        score += max(0.0, overload_ratio - 1.0) * 14.0
        score += max(0.0, monotony - 1.8) * 8.0
        score += max(0.0, strain - 50.0) * 0.18
        score += min(8.0, acute_ewma_load * 0.35)
        score += max(0.0, ewma_load_ratio - 1.05) * 15.0
        score += max(0.0, chronic_ewma_load - acute_ewma_load) * -0.2
        score -= (float(recovery_row.get("body_battery") or 50.0) - 50.0) * 0.18
        score -= (float(recovery_row.get("sleep_score") or 70.0) - 70.0) * 0.08
        score += float(feedback_row.get("fatigue_score") or 5) * 3.0
        score += float(feedback_row.get("stress_score") or 5) * 1.5
        score += float(feedback_row.get("soreness_score") or 4) * 2.5
        return float(round(max(0.0, min(score, 100.0)), 2))

    @staticmethod
    def _injury_risk_score_from_history(
        load_row: dict[str, Any],
        load_variability_row: dict[str, Any],
        acute_ewma_load: float,
        chronic_ewma_load: float,
        ewma_load_ratio: float,
        recovery_row: dict[str, Any],
        feedback_row: dict[str, Any],
        injury_row: dict[str, Any],
    ) -> float:
        last_7d = float(load_row.get("last_7d_distance_km") or 0.0)
        last_28d = float(load_row.get("last_28d_distance_km") or 0.0)
        cross_training_minutes = float(
            load_variability_row.get("last_7d_cross_training_minutes") or 0.0
        )
        monotony = CoachingHistoryService._training_monotony(load_variability_row)
        strain = CoachingHistoryService._training_strain(load_variability_row)
        baseline_weekly = last_28d / 4 if last_28d > 0 else 0.0
        overload_ratio = (last_7d / baseline_weekly) if baseline_weekly > 0 else 1.0
        score = 10.0
        score += max(0.0, overload_ratio - 1.1) * 16.0
        score += max(0.0, monotony - 2.0) * 7.0
        score += max(0.0, strain - 55.0) * 0.15
        score += min(8.0, cross_training_minutes * 0.02)
        score += min(6.0, acute_ewma_load * 0.25)
        score += max(0.0, ewma_load_ratio - 1.1) * 18.0
        score -= min(3.0, chronic_ewma_load * 0.08)
        score -= (float(recovery_row.get("body_battery") or 50.0) - 50.0) * 0.1
        score += float(feedback_row.get("soreness_score") or 4) * 3.0
        score += float(feedback_row.get("fatigue_score") or 5) * 1.2
        score += 12.0 if feedback_row.get("pain_notes") else 0.0
        score += float(injury_row.get("severity") or 0) * 5.0
        return float(round(max(0.0, min(score, 100.0)), 2))

    @staticmethod
    def _training_monotony(load_variability_row: dict[str, Any]) -> float:
        avg_daily_load = float(load_variability_row.get("avg_daily_load") or 0.0)
        sd_daily_load = float(load_variability_row.get("sd_daily_load") or 0.0)
        if avg_daily_load <= 0:
            return 0.0
        if sd_daily_load <= 0:
            return round(avg_daily_load, 2)
        return round(avg_daily_load / sd_daily_load, 2)

    @staticmethod
    def _training_strain(load_variability_row: dict[str, Any]) -> float:
        total_load = float(load_variability_row.get("total_load") or 0.0)
        if total_load <= 0:
            return 0.0
        return float(
            round(
                total_load * CoachingHistoryService._training_monotony(load_variability_row),
                2,
            )
        )

    @staticmethod
    def _ewma_load(rows: list[dict[str, Any]], span_days: int) -> float:
        if not rows:
            return 0.0
        alpha = 2.0 / (span_days + 1)
        ewma = 0.0
        for row in rows:
            load_value = float(row.get("load_units") or 0.0)
            ewma = (alpha * load_value) + ((1 - alpha) * ewma)
        return float(round(ewma, 2))

    @staticmethod
    def _ewma_ratio(acute_ewma_load: float, chronic_ewma_load: float) -> float:
        if chronic_ewma_load <= 0:
            return 1.0 if acute_ewma_load <= 0 else round(acute_ewma_load, 2)
        return float(round(acute_ewma_load / chronic_ewma_load, 2))
