"""End-to-end integration: mocked Gemini + real CoachingContextBuilder + real SafetyValidator.

Legacy fallback 도 mocked 로 두되, LLMDrivenPlanner 의 주요 분기를 통과시켜
메트릭·로그·안전 보정이 모두 작동하는지 검증한다.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from running_coach.coaching.context import CoachingContextBuilder
from running_coach.coaching.planners.llm_driven import LLMDrivenPlanner
from running_coach.coaching.safety import DEFAULT_SAFETY_RULES, SafetyValidator
from running_coach.coaching.safety import metrics as safety_metrics
from running_coach.models.config import RaceConfig
from running_coach.models.context import ActivityContext
from running_coach.models.health import HealthMetrics
from running_coach.models.metrics import AdvancedMetrics
from running_coach.models.performance import PerformanceMetrics

START = date(2026, 4, 20)


def _metrics() -> AdvancedMetrics:
    return AdvancedMetrics(
        date=START,
        health=HealthMetrics(),
        performance=PerformanceMetrics(),
        context=ActivityContext(),
    )


def _background() -> dict:
    return {
        "recent6Weeks": [],
        "recent12Months": [],
        "lifetime": {"totalRunCount": 100},
        "coachingState": {
            "readinessScore": 72,
            "fatigueScore": 45,
            "injuryRiskScore": 25,
            "load": {"chronicEwmaLoad": 45.0},
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


def _steps(session_type: str) -> list[dict]:
    base = {
        "durationUnit": "second",
        "targetType": "speed",
    }
    if session_type == "rest":
        return []
    if session_type == "quality":
        return [
            {"type": "Warmup", "durationValue": 900, "targetValue": "6:45", **base},
            {"type": "Interval", "durationValue": 240, "targetValue": "4:30", **base},
            {"type": "Recovery", "durationValue": 120, "targetValue": "7:20", **base},
            {"type": "Cooldown", "durationValue": 600, "targetValue": "7:10", **base},
        ]
    if session_type == "long_run":
        return [
            {"type": "Warmup", "durationValue": 600, "targetValue": "6:45", **base},
            {"type": "Run", "durationValue": 3600, "targetValue": "6:40", **base},
            {"type": "Cooldown", "durationValue": 300, "targetValue": "7:10", **base},
        ]
    if session_type == "recovery":
        return [
            {"type": "Warmup", "durationValue": 300, "targetValue": "6:45", **base},
            {"type": "Run", "durationValue": 1500, "targetValue": "7:20", **base},
            {"type": "Cooldown", "durationValue": 300, "targetValue": "7:10", **base},
        ]
    return [
        {"type": "Warmup", "durationValue": 600, "targetValue": "6:45", **base},
        {"type": "Run", "durationValue": 1800, "targetValue": "6:45", **base},
        {"type": "Cooldown", "durationValue": 300, "targetValue": "7:10", **base},
    ]


def _plan_json(session_types: list[str]) -> dict:
    names = {
        "rest": "Rest Day",
        "recovery": "Recovery Run",
        "base": "Base Run",
        "quality": "Quality Session",
        "long_run": "Long Run",
    }
    days = []
    for i, st in enumerate(session_types):
        steps = _steps(st)
        total = sum(s["durationValue"] for s in steps) // 60
        days.append(
            {
                "date": (START + timedelta(days=i)).isoformat(),
                "sessionType": st,
                "plannedMinutes": total,
                "workout": {
                    "workoutName": names[st],
                    "description": "integration test",
                    "sportType": "RUNNING",
                    "steps": steps,
                },
            }
        )
    return {
        "weekly": {
            "summaryKo": "end-to-end",
            "phase": "build",
            "phaseReasonKo": "테스트",
            "weeklyVolumeTargetKm": 42.0,
            "riskAcknowledgements": [],
        },
        "plan": days,
    }


def _gemini_response(payload: dict):
    resp = MagicMock()
    resp.text = json.dumps(payload)
    return resp


@pytest.fixture(autouse=True)
def reset_metrics():
    safety_metrics.reset_counters_for_test()
    yield
    safety_metrics.reset_counters_for_test()


@pytest.fixture
def history_mock():
    history = MagicMock()
    history.summarize_training_background.return_value = _background()
    history.list_recent_completed_activities.return_value = [
        {
            "activityDate": "2026-04-19",
            "plannedCategory": "base",
            "actualCategory": "base",
            "distanceKm": 8.5,
            "durationSeconds": 2800,
            "avgPace": "5:45",
            "avgHr": 140,
            "executionStatus": "completed_as_planned",
            "deviationReason": None,
            "coachInterpretation": "정상",
            "targetMatchScore": 0.88,
        }
    ]
    return history


@pytest.fixture
def integration_planner(history_mock):
    context_builder = CoachingContextBuilder(history_service=history_mock)
    validator = SafetyValidator(rules=list(DEFAULT_SAFETY_RULES))
    gemini = MagicMock()
    legacy = MagicMock()
    legacy._parse_response = lambda text: json.loads(text)
    legacy.generate_plan.return_value = None
    return (
        LLMDrivenPlanner(
            gemini_client=gemini,
            context_builder=context_builder,
            safety_validator=validator,
            legacy_fallback=legacy,
        ),
        gemini,
        legacy,
    )


class TestEndToEnd:
    def test_full_pipeline_with_safe_plan_increments_metric(self, integration_planner):
        planner, gemini, _ = integration_planner
        safe = _plan_json(["base", "quality", "base", "recovery", "base", "long_run", "rest"])
        gemini.models.generate_content.return_value = _gemini_response(safe)

        plan = planner.generate_plan(_metrics(), RaceConfig(), replan_reasons=["x"])

        assert plan is not None
        assert plan.plan[1].session_type == "quality"
        assert safety_metrics.plan_generated_counter["llm_driven"] == 1
        assert sum(safety_metrics.violation_counter.values()) == 0

    def test_unsafe_plan_records_violation_metrics(self, integration_planner):
        planner, gemini, _ = integration_planner
        unsafe = _plan_json(["quality", "quality", "base", "base", "base", "long_run", "rest"])
        gemini.models.generate_content.return_value = _gemini_response(unsafe)

        plan = planner.generate_plan(_metrics(), RaceConfig())

        assert plan is not None
        # 보정됨
        assert plan.plan[1].session_type != "quality"
        # 위반 카운터에 no_back_to_back_quality 기록
        assert safety_metrics.violation_counter[("no_back_to_back_quality", "block")] >= 1
        assert safety_metrics.plan_generated_counter["llm_driven"] == 1

    def test_parse_failure_does_not_bump_plan_counter(self, integration_planner):
        planner, gemini, legacy = integration_planner
        bad = MagicMock()
        bad.text = "{not json"
        gemini.models.generate_content.return_value = bad

        planner.generate_plan(_metrics(), RaceConfig())

        # fallback 호출만 발생; plan_generated 카운터는 0
        legacy.generate_plan.assert_called_once()
        assert safety_metrics.plan_generated_counter["llm_driven"] == 0

    def test_context_builder_receives_replan_reasons(self, integration_planner, history_mock):
        planner, gemini, _ = integration_planner
        safe = _plan_json(["base", "quality", "base", "recovery", "base", "long_run", "rest"])
        gemini.models.generate_content.return_value = _gemini_response(safe)

        planner.generate_plan(
            _metrics(), RaceConfig(), replan_reasons=["missed_key_workout", "new_activity"]
        )

        # 프롬프트에 replan reasons 가 포함됐는지 확인
        call_args = gemini.models.generate_content.call_args
        prompt = call_args.kwargs["contents"]
        assert "missed_key_workout" in prompt
        assert "new_activity" in prompt
