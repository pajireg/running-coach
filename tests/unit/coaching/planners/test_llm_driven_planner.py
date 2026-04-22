"""LLMDrivenPlanner: context → prompt → gemini → SafetyValidator 파이프라인."""

from __future__ import annotations

import json
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from running_coach.coaching.context import CoachingContextBuilder
from running_coach.coaching.planners.llm_driven import LLMDrivenPlanner
from running_coach.coaching.safety import DEFAULT_SAFETY_RULES, SafetyValidator
from running_coach.exceptions import GeminiQuotaExceededError
from running_coach.models.config import RaceConfig
from running_coach.models.context import ActivityContext
from running_coach.models.health import HealthMetrics
from running_coach.models.metrics import AdvancedMetrics
from running_coach.models.performance import PerformanceMetrics

START = date(2026, 4, 20)
MOCK_BACKGROUND = {
    "recent6Weeks": [],
    "recent12Months": [],
    "lifetime": {},
    "coachingState": {
        "readinessScore": 70,
        "fatigueScore": 40,
        "injuryRiskScore": 20,
        "load": {"chronicEwmaLoad": 50.0},
        "activeInjury": {"severity": 0},
        "subjectiveFeedback": {},
    },
    "planningConstraints": {
        "availability": [
            {"weekday": i, "isAvailable": True, "maxDurationMinutes": 180} for i in range(7)
        ],
        "trainingBlock": {},
        "raceGoal": {},
    },
}


def _metrics() -> AdvancedMetrics:
    return AdvancedMetrics(
        date=START,
        health=HealthMetrics(),
        performance=PerformanceMetrics(),
        context=ActivityContext(),
    )


def _default_steps(session_type: str) -> list[dict]:
    if session_type == "rest":
        return []
    if session_type == "quality":
        return [
            {
                "type": "Warmup",
                "durationValue": 900,
                "durationUnit": "second",
                "targetType": "speed",
                "targetValue": "6:45",
            },
            {
                "type": "Interval",
                "durationValue": 240,
                "durationUnit": "second",
                "targetType": "speed",
                "targetValue": "4:30",
            },
            {
                "type": "Recovery",
                "durationValue": 120,
                "durationUnit": "second",
                "targetType": "speed",
                "targetValue": "7:20",
            },
            {
                "type": "Cooldown",
                "durationValue": 600,
                "durationUnit": "second",
                "targetType": "speed",
                "targetValue": "7:10",
            },
        ]
    if session_type == "long_run":
        return [
            {
                "type": "Warmup",
                "durationValue": 600,
                "durationUnit": "second",
                "targetType": "speed",
                "targetValue": "6:45",
            },
            {
                "type": "Run",
                "durationValue": 3600,
                "durationUnit": "second",
                "targetType": "speed",
                "targetValue": "6:40",
            },
            {
                "type": "Cooldown",
                "durationValue": 300,
                "durationUnit": "second",
                "targetType": "speed",
                "targetValue": "7:10",
            },
        ]
    if session_type == "recovery":
        return [
            {
                "type": "Warmup",
                "durationValue": 300,
                "durationUnit": "second",
                "targetType": "speed",
                "targetValue": "6:45",
            },
            {
                "type": "Run",
                "durationValue": 1500,
                "durationUnit": "second",
                "targetType": "speed",
                "targetValue": "7:20",
            },
            {
                "type": "Cooldown",
                "durationValue": 300,
                "durationUnit": "second",
                "targetType": "speed",
                "targetValue": "7:10",
            },
        ]
    return [
        {
            "type": "Warmup",
            "durationValue": 600,
            "durationUnit": "second",
            "targetType": "speed",
            "targetValue": "6:45",
        },
        {
            "type": "Run",
            "durationValue": 1800,
            "durationUnit": "second",
            "targetType": "speed",
            "targetValue": "6:45",
        },
        {
            "type": "Cooldown",
            "durationValue": 300,
            "durationUnit": "second",
            "targetType": "speed",
            "targetValue": "7:10",
        },
    ]


def _plan_json(session_types: list[str]) -> dict:
    names = {
        "rest": "Rest Day",
        "recovery": "Recovery Run",
        "base": "Base Run",
        "quality": "Interval",
        "long_run": "Long Run",
    }
    days = []
    for i, st in enumerate(session_types):
        steps = _default_steps(st)
        total_minutes = sum(s["durationValue"] for s in steps) // 60
        days.append(
            {
                "date": (START + timedelta(days=i)).isoformat(),
                "sessionType": st,
                "plannedMinutes": total_minutes,
                "workout": {
                    "workoutName": names[st],
                    "description": "test",
                    "sportType": "RUNNING",
                    "steps": steps,
                },
            }
        )
    return {
        "weekly": {
            "summaryKo": "test week",
            "phase": "build",
            "phaseReasonKo": "test",
            "weeklyVolumeTargetKm": 40.0,
            "riskAcknowledgements": [],
        },
        "plan": days,
    }


def _fake_gemini_response(payload: dict):
    resp = MagicMock()
    resp.text = json.dumps(payload)
    return resp


@pytest.fixture
def mock_gemini():
    client = MagicMock()
    return client


@pytest.fixture
def builder():
    history = MagicMock()
    history.summarize_training_background.return_value = MOCK_BACKGROUND
    history.list_recent_completed_activities.return_value = []
    return CoachingContextBuilder(history_service=history)


@pytest.fixture
def validator():
    return SafetyValidator(rules=list(DEFAULT_SAFETY_RULES))


@pytest.fixture
def legacy_fallback():
    inner = MagicMock()
    inner.generate_plan.return_value = None
    return inner


@pytest.fixture
def planner(mock_gemini, builder, validator, legacy_fallback):
    return LLMDrivenPlanner(
        gemini_client=mock_gemini,
        context_builder=builder,
        safety_validator=validator,
        legacy_fallback=legacy_fallback,
    )


class TestHappyPath:
    def test_safe_plan_passes_through(self, planner, mock_gemini):
        safe = _plan_json(["base", "quality", "base", "recovery", "base", "long_run", "rest"])
        mock_gemini.models.generate_content.return_value = _fake_gemini_response(safe)
        plan = planner.generate_plan(_metrics(), RaceConfig(), replan_reasons=["x"])
        assert plan is not None
        assert plan.plan[1].session_type == "quality"
        assert plan.plan[5].session_type == "long_run"
        assert plan.weekly is not None
        assert plan.weekly.phase == "build"

    def test_unsafe_plan_gets_auto_corrected(self, planner, mock_gemini):
        """연속 quality → 두 번째가 recovery 로 강등."""
        unsafe = _plan_json(["quality", "quality", "base", "base", "base", "long_run", "rest"])
        mock_gemini.models.generate_content.return_value = _fake_gemini_response(unsafe)
        plan = planner.generate_plan(_metrics(), RaceConfig())
        assert plan is not None
        assert plan.plan[1].session_type != "quality"  # 보정됨

    def test_empty_rest_day_accepted(self, planner, mock_gemini):
        safe = _plan_json(["rest", "base", "quality", "base", "recovery", "long_run", "rest"])
        mock_gemini.models.generate_content.return_value = _fake_gemini_response(safe)
        plan = planner.generate_plan(_metrics(), RaceConfig())
        assert plan is not None


class TestFallback:
    def test_quota_exceeded_falls_back(self, planner, mock_gemini, legacy_fallback):
        mock_gemini.models.generate_content.side_effect = GeminiQuotaExceededError("quota")
        planner.generate_plan(_metrics(), RaceConfig())
        legacy_fallback.generate_plan.assert_called_once()

    def test_gemini_exception_falls_back(self, planner, mock_gemini, legacy_fallback):
        mock_gemini.models.generate_content.side_effect = RuntimeError("network")
        planner.generate_plan(_metrics(), RaceConfig())
        legacy_fallback.generate_plan.assert_called_once()

    def test_invalid_json_falls_back(self, planner, mock_gemini, legacy_fallback):
        bad = MagicMock()
        bad.text = "{not json"
        mock_gemini.models.generate_content.return_value = bad
        planner.generate_plan(_metrics(), RaceConfig())
        legacy_fallback.generate_plan.assert_called_once()

    def test_missing_required_fields_falls_back(self, planner, mock_gemini, legacy_fallback):
        """plan 필드 누락 → Pydantic 실패 → fallback."""
        mock_gemini.models.generate_content.return_value = _fake_gemini_response(
            {"weekly": {}, "plan": []}
        )
        planner.generate_plan(_metrics(), RaceConfig())
        legacy_fallback.generate_plan.assert_called_once()

    def test_empty_response_falls_back(self, planner, mock_gemini, legacy_fallback):
        empty = MagicMock()
        empty.text = ""
        mock_gemini.models.generate_content.return_value = empty
        planner.generate_plan(_metrics(), RaceConfig())
        legacy_fallback.generate_plan.assert_called_once()


class TestSafetyIntegration:
    def test_all_safety_rules_respected_in_final_plan(self, planner, mock_gemini):
        unsafe = _plan_json(["quality", "long_run", "quality", "base", "base", "quality", "base"])
        mock_gemini.models.generate_content.return_value = _fake_gemini_response(unsafe)
        plan = planner.generate_plan(_metrics(), RaceConfig())
        # 최종적으로 validator 에 통과해야 함
        assert plan is not None
        validator = SafetyValidator(rules=list(DEFAULT_SAFETY_RULES))
        ctx = planner._context_builder.build(_metrics(), RaceConfig())
        result = validator.validate(plan, ctx)
        assert not result.unresolvable
