"""CoachingContextBuilder 가 history_service 출력을 올바른 context 로 변환."""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest

from running_coach.coaching.context import (
    CoachingContext,
    CoachingContextBuilder,
    ExecutionDay,
    FeedbackSnapshot,
    InjurySnapshot,
    RaceGoalSnapshot,
    TrainingBackground,
    TrainingBlockSnapshot,
)
from running_coach.core.pace_zones import PaceZones
from running_coach.models.config import RaceConfig
from running_coach.models.context import ActivityContext
from running_coach.models.health import HealthMetrics
from running_coach.models.metrics import AdvancedMetrics
from running_coach.models.performance import PerformanceMetrics

STABLE_DATE = date(2026, 4, 20)


def _metrics(as_of: date = STABLE_DATE) -> AdvancedMetrics:
    return AdvancedMetrics(
        date=as_of,
        health=HealthMetrics(),
        performance=PerformanceMetrics(),
        context=ActivityContext(),
    )


FULL_BACKGROUND: dict[str, Any] = {
    "recent6Weeks": [
        {"weekStart": "2026-03-09", "distanceKm": 32.1, "runCount": 4, "longRunKm": 12.5},
        {"weekStart": "2026-03-16", "distanceKm": 40.0, "runCount": 5, "longRunKm": 15.0},
    ],
    "recent12Months": [
        {"monthStart": "2026-04-01", "distanceKm": 145.0, "runCount": 18},
    ],
    "lifetime": {
        "totalRunCount": 512,
        "totalDistanceKm": 4120.0,
        "longestRunKm": 35.0,
        "firstRunDate": "2022-06-01",
    },
    "coachingState": {
        "readinessScore": 68.0,
        "fatigueScore": 52.0,
        "injuryRiskScore": 30.0,
        "load": {
            "last7dDistanceKm": 30.0,
            "chronicEwmaLoad": 45.0,
        },
        "activeInjury": {
            "injuryArea": "right knee",
            "severity": 4,
            "statusDate": "2026-04-14",
            "notes": "통증 지속",
        },
        "subjectiveFeedback": {
            "feedbackDate": "2026-04-18",
            "fatigueScore": 6,
            "sorenessScore": 5,
            "stressScore": 4,
            "motivationScore": 7,
            "sleepQualityScore": 6,
            "painNotes": "무릎 바깥쪽 살짝",
            "notes": None,
        },
    },
    "planningConstraints": {
        "availability": [
            {
                "weekday": 0,
                "isAvailable": True,
                "maxDurationMinutes": 60,
                "preferredSessionType": "base",
            },
            {
                "weekday": 5,
                "isAvailable": True,
                "maxDurationMinutes": 180,
                "preferredSessionType": "long_run",
            },
        ],
        "trainingBlock": {
            "phase": "build",
            "focus": "aerobic capacity",
            "startsOn": "2026-04-01",
            "endsOn": "2026-04-28",
            "weeklyVolumeTargetKm": 55.0,
        },
        "raceGoal": {
            "goalName": "Spring Half",
            "raceDate": "2026-05-17",
            "distance": "Half",
            "goalTime": "1:45:00",
            "targetPace": "4:58",
        },
    },
}


def _build_mock_history(background: dict[str, Any] | None = None) -> MagicMock:
    mock = MagicMock()
    mock.summarize_training_background.return_value = (
        background if background is not None else FULL_BACKGROUND
    )
    mock.list_recent_completed_activities.return_value = [
        {
            "activityDate": "2026-04-19",
            "plannedCategory": "long_run",
            "actualCategory": "long_run",
            "distanceKm": 18.2,
            "durationSeconds": 6840,
            "avgPace": "6:15",
            "avgHr": 148,
            "executionStatus": "completed_as_planned",
            "deviationReason": None,
            "coachInterpretation": "계획대로 수행",
            "targetMatchScore": 0.9,
        },
        {
            "activityDate": "2026-04-17",
            "plannedCategory": "quality",
            "actualCategory": "quality",
            "distanceKm": 9.5,
            "durationSeconds": 2760,
            "avgPace": "4:50",
            "avgHr": 165,
            "executionStatus": "completed_as_planned",
            "deviationReason": None,
            "coachInterpretation": None,
            "targetMatchScore": 0.85,
        },
    ]
    return mock


@pytest.fixture
def builder() -> CoachingContextBuilder:
    history = _build_mock_history()
    return CoachingContextBuilder(history_service=history)


@pytest.fixture
def race() -> RaceConfig:
    return RaceConfig(
        date=date(2026, 5, 17),
        distance="Half",
        goal_time="1:45:00",
        target_pace="4:58",
    )


class TestCoachingContextBuilder:
    def test_returns_coaching_context(self, builder, race):
        ctx = builder.build(metrics=_metrics(), race_config=race, replan_reasons=["x"])
        assert isinstance(ctx, CoachingContext)
        assert ctx.today == STABLE_DATE
        assert ctx.metrics is not None

    def test_scores_populated_from_coaching_state(self, builder, race):
        ctx = builder.build(_metrics(), race)
        assert ctx.scores.readiness == 68.0
        assert ctx.scores.fatigue == 52.0
        assert ctx.scores.injury_risk == 30.0
        assert ctx.scores.active_injury_severity == 4
        assert ctx.scores.chronic_ewma_load == 45.0

    def test_pace_zones_derived_from_race_target(self, builder, race):
        ctx = builder.build(_metrics(), race)
        assert isinstance(ctx.pace_zones, PaceZones)
        # race target pace 4:58 = 298s → interval 273s = 4:33
        assert ctx.pace_zones.interval == "4:33"
        assert ctx.pace_profile is not None
        assert ctx.pace_profile.threshold_basis == "race_target_pace"
        assert ctx.pace_profile.bands["interval"].fast == "4:08"

    def test_availability_map_keyed_by_weekday(self, builder, race):
        ctx = builder.build(_metrics(), race)
        assert 0 in ctx.availability
        assert ctx.availability[0].max_duration_minutes == 60
        assert ctx.availability[5].preferred_session_type == "long_run"

    def test_execution_history_14d_populated(self, builder, race):
        ctx = builder.build(_metrics(), race)
        assert len(ctx.execution_history_14d) == 2
        first = ctx.execution_history_14d[0]
        assert isinstance(first, ExecutionDay)
        assert first.date == date(2026, 4, 19)
        assert first.actual_category == "long_run"
        assert first.distance_km == 18.2
        assert first.match_score == 0.9

    def test_active_injury_detected(self, builder, race):
        ctx = builder.build(_metrics(), race)
        assert isinstance(ctx.active_injury, InjurySnapshot)
        assert ctx.active_injury.is_active
        assert ctx.active_injury.severity == 4
        assert ctx.active_injury.injury_area == "right knee"

    def test_recent_feedback_with_staleness(self, builder, race):
        ctx = builder.build(_metrics(), race)
        assert len(ctx.recent_feedback) == 1
        fb = ctx.recent_feedback[0]
        assert isinstance(fb, FeedbackSnapshot)
        assert fb.fatigue_score == 6
        assert fb.staleness_days == (STABLE_DATE - date(2026, 4, 18)).days

    def test_training_block_populated(self, builder, race):
        ctx = builder.build(_metrics(), race)
        assert isinstance(ctx.training_block, TrainingBlockSnapshot)
        assert ctx.training_block.phase == "build"
        assert ctx.training_block.weekly_volume_target_km == 55.0

    def test_race_goal_populated(self, builder, race):
        ctx = builder.build(_metrics(), race)
        assert isinstance(ctx.race_goal, RaceGoalSnapshot)
        assert ctx.race_goal.distance == "Half"
        assert ctx.race_goal.race_date == date(2026, 5, 17)

    def test_training_background_carried_through(self, builder, race):
        ctx = builder.build(_metrics(), race)
        assert isinstance(ctx.training_background, TrainingBackground)
        assert len(ctx.training_background.recent_6_weeks) == 2
        assert ctx.training_background.lifetime["totalRunCount"] == 512

    def test_replan_reasons_passed_through(self, builder, race):
        ctx = builder.build(_metrics(), race, replan_reasons=["missed_key_workout"])
        assert ctx.replan_reasons == ["missed_key_workout"]

    def test_empty_replan_reasons_when_none(self, builder, race):
        ctx = builder.build(_metrics(), race)
        assert ctx.replan_reasons == []


class TestBuilderHandlesMissingData:
    def test_no_injury_returns_inactive_snapshot(self, race):
        background = {**FULL_BACKGROUND}
        background["coachingState"] = {
            **FULL_BACKGROUND["coachingState"],
            "activeInjury": {"severity": 0},
        }
        history = _build_mock_history(background=background)
        builder = CoachingContextBuilder(history_service=history)
        ctx = builder.build(_metrics(), race)
        assert not ctx.active_injury.is_active
        assert ctx.scores.active_injury_severity == 0

    def test_no_feedback_returns_empty_list(self, race):
        background = {**FULL_BACKGROUND}
        background["coachingState"] = {
            **FULL_BACKGROUND["coachingState"],
            "subjectiveFeedback": {},
        }
        history = _build_mock_history(background=background)
        builder = CoachingContextBuilder(history_service=history)
        ctx = builder.build(_metrics(), race)
        assert ctx.recent_feedback == []

    def test_no_race_goal_returns_none(self, race):
        background = {**FULL_BACKGROUND}
        background["planningConstraints"] = {
            **FULL_BACKGROUND["planningConstraints"],
            "raceGoal": {},
        }
        history = _build_mock_history(background=background)
        builder = CoachingContextBuilder(history_service=history)
        ctx = builder.build(_metrics(), race)
        assert ctx.race_goal is None

    def test_no_training_block_returns_none(self, race):
        background = {**FULL_BACKGROUND}
        background["planningConstraints"] = {
            **FULL_BACKGROUND["planningConstraints"],
            "trainingBlock": {"phase": None},
        }
        history = _build_mock_history(background=background)
        builder = CoachingContextBuilder(history_service=history)
        ctx = builder.build(_metrics(), race)
        assert ctx.training_block is None

    def test_empty_activity_history_returns_empty_list(self, race):
        history = _build_mock_history()
        history.list_recent_completed_activities.return_value = []
        builder = CoachingContextBuilder(history_service=history)
        ctx = builder.build(_metrics(), race)
        assert ctx.execution_history_14d == []
