from datetime import date

from running_coach.models.feedback import SubjectiveFeedback
from running_coach.storage.history_service import CoachingHistoryService


class _FakeDb:
    pass


class _SummaryHistoryService(CoachingHistoryService):
    def _athlete_id(self) -> str:  # type: ignore[override]
        return "athlete-1"

    def _fetchall(self, query: str, params: dict[str, object]):  # type: ignore[override]
        if "date_trunc('week'" in query:
            return [
                {
                    "week_start": date(2026, 4, 13),
                    "distance_km": 42.5,
                    "run_count": 5,
                    "long_run_km": 18.0,
                }
            ]
        if "date_trunc('month'" in query:
            return [
                {
                    "month_start": date(2026, 4, 1),
                    "distance_km": 120.0,
                    "run_count": 14,
                }
            ]
        if "FROM availability_rules" in query:
            return [
                {
                    "weekday": 2,
                    "is_available": True,
                    "max_duration_minutes": 45,
                    "preferred_session_type": "quality",
                },
                {
                    "weekday": 6,
                    "is_available": True,
                    "max_duration_minutes": 90,
                    "preferred_session_type": "long_run",
                },
            ]
        return []

    def _fetchone(self, query: str, params: dict[str, object]):  # type: ignore[override]
        if "COUNT(*) AS total_run_count" in query:
            return {
                "total_run_count": 200,
                "total_distance_km": 1800.5,
                "longest_run_km": 30.2,
                "first_run_date": date(2024, 1, 1),
            }
        if "SUM(CASE" in query:
            return {
                "last_7d_distance_km": 40.0,
                "last_28d_distance_km": 120.0,
                "last_7d_run_count": 5,
                "last_long_run_date": date(2026, 4, 13),
                "last_quality_date": date(2026, 4, 15),
            }
        if "WITH recent_plans AS" in query:
            return {
                "planned_workout_count": 6,
                "matched_workout_count": 5,
                "skipped_workout_count": 1,
                "avg_completion_ratio": 0.96,
                "avg_target_match_score": 0.91,
                "unplanned_run_count": 1,
            }
        if "FROM subjective_feedback" in query:
            return {
                "feedback_date": date(2026, 4, 17),
                "fatigue_score": 4,
                "soreness_score": 3,
                "stress_score": 5,
                "motivation_score": 8,
                "sleep_quality_score": 7,
                "pain_notes": None,
                "notes": "컨디션 양호",
            }
        if "FROM injury_status" in query:
            return {}
        if "FROM race_goals" in query:
            return {
                "goal_name": "10K PB",
                "race_date": date(2026, 5, 10),
                "distance": "10K",
                "goal_time": "49:00",
                "target_pace": "4:54",
                "priority": 1,
            }
        if "FROM training_blocks" in query:
            return {
                "phase": "build",
                "starts_on": date(2026, 4, 1),
                "ends_on": date(2026, 4, 30),
                "focus": "10K speed",
                "weekly_volume_target_km": 42.0,
            }
        return None


class _RecordingHistoryService(CoachingHistoryService):
    def __init__(self):
        super().__init__(_FakeDb(), "user@example.com")
        self.executed: list[tuple[str, dict[str, object]]] = []

    def _athlete_id(self) -> str:  # type: ignore[override]
        return "athlete-1"

    def _execute(self, query: str, params: dict[str, object]) -> None:  # type: ignore[override]
        self.executed.append((query, params))


def test_summarize_training_background_returns_recent_and_lifetime_sections():
    service = _SummaryHistoryService(_FakeDb(), "user@example.com")

    summary = service.summarize_training_background(date(2026, 4, 17))

    assert summary["recent6Weeks"][0]["distanceKm"] == 42.5
    assert summary["recent12Months"][0]["runCount"] == 14
    assert summary["lifetime"]["totalRunCount"] == 200
    assert summary["lifetime"]["firstRunDate"] == "2024-01-01"
    assert summary["coachingState"]["adherence"]["matchedWorkoutCount"] == 5
    assert summary["planningConstraints"]["raceGoal"]["distance"] == "10K"
    assert summary["planningConstraints"]["trainingBlock"]["phase"] == "build"


def test_planned_workout_category_and_target_match_score():
    planned = {
        "workout_name": "Running Coach: Threshold Session",
        "plan_payload": {
            "workout": {
                "steps": [
                    {"type": "Warmup"},
                    {"type": "Interval"},
                ]
            }
        },
    }

    category = CoachingHistoryService._planned_workout_category(planned)
    score = CoachingHistoryService._target_match_score(
        planned_category="quality",
        actual_category="quality",
        target_duration=3600,
        actual_duration=3300,
    )

    assert category == "quality"
    assert score == 0.94


def test_summarize_coaching_state_combines_load_feedback_and_adherence():
    service = _SummaryHistoryService(_FakeDb(), "user@example.com")

    state = service.summarize_coaching_state(date(2026, 4, 17))

    assert state["adherenceWindowDays"] == 42
    assert state["meaningfulMatchThreshold"] == 0.75
    assert state["historyConfidence"] == 1.0
    assert state["load"]["last7dDistanceKm"] == 40.0
    assert state["load"]["daysSinceQuality"] == 2
    assert state["subjectiveFeedback"]["motivationScore"] == 8
    assert state["adherence"]["avgTargetMatchScore"] == 0.91
    assert state["adherence"]["executionRate"] == 0.83
    assert state["readinessScore"] > 0
    assert state["fatigueScore"] > state["injuryRiskScore"]


def test_record_subjective_feedback_uses_upsert_query():
    service = _RecordingHistoryService()
    feedback = SubjectiveFeedback(
        feedbackDate="2026-04-17",
        fatigueScore=4,
        sorenessScore=3,
        stressScore=5,
        motivationScore=8,
        sleepQualityScore=7,
        painNotes="없음",
        notes="테스트",
    )

    service.record_subjective_feedback(feedback)

    _, params = service.executed[0]
    assert params["feedback_date"] == date(2026, 4, 17)
    assert params["motivation_score"] == 8


def test_planned_match_score_prefers_same_category_and_day():
    candidate = {
        "workout_name": "Running Coach: Interval Session",
        "total_duration_seconds": 3600,
        "plan_payload": {"workout": {"steps": [{"type": "Interval"}]}},
        "workout_date": date(2026, 4, 17),
        "already_matched": False,
    }

    score = CoachingHistoryService(_FakeDb(), "user@example.com")._planned_match_score(
        activity_date=date(2026, 4, 17),
        candidate=candidate,
        actual_category="quality",
        actual_duration=3300,
    )

    assert score > 0.9


class _SelectionHistoryService(CoachingHistoryService):
    def __init__(self):
        super().__init__(_FakeDb(), "user@example.com")

    def _fetchall(self, query: str, params: dict[str, object]):  # type: ignore[override]
        if "FROM planned_workouts pw" in query:
            return [
                {
                    "planned_workout_id": "pw-1",
                    "total_duration_seconds": 1800,
                    "workout_name": "Running Coach: Recovery Run",
                    "plan_payload": {"workout": {"steps": [{"type": "Run"}]}},
                    "workout_date": date(2026, 4, 17),
                    "already_matched": False,
                }
            ]
        return []


def test_select_best_planned_workout_rejects_low_quality_category_mismatch():
    service = _SelectionHistoryService()

    selected = service._select_best_planned_workout(
        athlete_id="athlete-1",
        activity_date=date(2026, 4, 16),
        actual_category="quality",
        actual_duration=1700,
    )

    assert selected is None


def test_adherence_history_confidence_scales_with_plan_count():
    assert CoachingHistoryService._adherence_history_confidence(0) == 0.0
    assert CoachingHistoryService._adherence_history_confidence(2) == 0.5
    assert CoachingHistoryService._adherence_history_confidence(6) == 1.0


def test_extract_started_at_keeps_local_timezone_for_naive_garmin_time():
    started_at = CoachingHistoryService._extract_started_at(
        {"startTimeLocal": "2026-04-11 16:03:55"}
    )

    assert started_at is not None
    assert started_at.isoformat() == "2026-04-11T16:03:55+09:00"


def test_execution_status_classification():
    assert (
        CoachingHistoryService._execution_status("quality", "quality", 0.95, 0.88)
        == "completed_as_planned"
    )
    assert (
        CoachingHistoryService._execution_status("recovery", "base", 0.92, 0.72)
        == "completed_substituted"
    )
    assert (
        CoachingHistoryService._execution_status("base", "base", 0.5, 0.6)
        == "completed_partial"
    )
    assert (
        CoachingHistoryService._execution_status("unplanned", "base", None, 0.0)
        == "completed_unplanned"
    )
