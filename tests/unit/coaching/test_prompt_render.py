"""LLMPromptTemplate 렌더링 스냅샷·섹션 테스트."""

from __future__ import annotations

import json
from datetime import date

import pytest

from running_coach.coaching.context import (
    AvailabilitySlot,
    CoachingContext,
    CoachingScores,
    ExecutionDay,
    FeedbackSnapshot,
    InjurySnapshot,
    RaceGoalSnapshot,
    TrainingBackground,
    TrainingBlockSnapshot,
)
from running_coach.coaching.prompt import OUTPUT_SCHEMA, LLMPromptTemplate
from running_coach.coaching.safety import DEFAULT_SAFETY_RULES, SafetyValidator
from running_coach.core.pace_zones import PaceZones
from running_coach.models.context import ActivityContext
from running_coach.models.health import HealthMetrics
from running_coach.models.metrics import AdvancedMetrics
from running_coach.models.performance import PerformanceMetrics

ZONES = PaceZones(
    interval="4:30",
    threshold="5:00",
    tempo="5:15",
    base="6:45",
    long_run="6:40",
    recovery="7:20",
    warmup="6:45",
    cooldown="7:10",
)


def _metrics() -> AdvancedMetrics:
    return AdvancedMetrics(
        date=date(2026, 4, 20),
        health=HealthMetrics(),
        performance=PerformanceMetrics(),
        context=ActivityContext(),
    )


def _full_ctx() -> CoachingContext:
    return CoachingContext(
        today=date(2026, 4, 20),
        metrics=_metrics(),
        scores=CoachingScores(
            readiness=68,
            fatigue=52,
            injury_risk=30,
            active_injury_severity=4,
            chronic_ewma_load=45.0,
        ),
        pace_zones=ZONES,
        availability={
            0: AvailabilitySlot(weekday=0, is_available=True, max_duration_minutes=60),
            5: AvailabilitySlot(
                weekday=5,
                is_available=True,
                max_duration_minutes=180,
                preferred_session_type="long_run",
            ),
        },
        execution_history_14d=[
            ExecutionDay(
                date=date(2026, 4, 19),
                planned_category="long_run",
                actual_category="long_run",
                distance_km=18.2,
                duration_seconds=6840,
                avg_pace="6:15",
                avg_hr=148,
                execution_status="completed_as_planned",
                match_score=0.9,
            ),
        ],
        active_injury=InjurySnapshot(
            injury_area="right knee",
            severity=4,
            status_date=date(2026, 4, 14),
            notes="통증 지속",
        ),
        recent_feedback=[
            FeedbackSnapshot(
                feedback_date=date(2026, 4, 18),
                fatigue_score=6,
                soreness_score=5,
                staleness_days=2,
            )
        ],
        training_block=TrainingBlockSnapshot(
            phase="build",
            weekly_volume_target_km=55.0,
            starts_on=date(2026, 4, 1),
            ends_on=date(2026, 4, 28),
        ),
        race_goal=RaceGoalSnapshot(
            goal_name="Spring Half",
            race_date=date(2026, 5, 17),
            distance="Half",
            goal_time="1:45:00",
            target_pace="4:58",
        ),
        training_background=TrainingBackground(
            recent_6_weeks=[{"weekStart": "2026-03-09", "distanceKm": 32.1}],
            lifetime={"totalRunCount": 512},
        ),
        replan_reasons=["missed_key_workout"],
    )


SAFETY_RULES = [
    "quality/long_run 세션 사이 최소 1일 간격을 둡니다.",
    "7일 계획 범위에서 최소 1일 휴식을 보장합니다.",
    "모든 step pace 는 pace safety band 안에서 선택합니다.",
]


@pytest.fixture
def rendered() -> str:
    return LLMPromptTemplate.render(_full_ctx(), safety_rules=SAFETY_RULES)


class TestPromptSections:
    def test_contains_role_statement(self, rendered):
        assert "시니어 러닝 코치" in rendered

    def test_contains_today_and_end_date(self, rendered):
        assert "2026-04-20" in rendered
        assert "2026-04-26" in rendered  # today + 6

    def test_contains_rolling_horizon_context(self, rendered):
        assert "rolling 7-day horizon" in rendered
        assert "매일 체크인" in rendered
        assert "오늘부터 이어지는 7일치 훈련" in rendered
        assert "현재 7일 흐름 안에서 맡는 역할" in rendered

    def test_does_not_prompt_with_calendar_week_ban_examples(self, rendered):
        assert "금주" not in rendered
        assert "이번 주 마무리" not in rendered
        assert "다음 주 준비" not in rendered
        assert "캘린더 주간을 닫는 표현" not in rendered

    def test_default_safety_rules_use_rolling_horizon_language(self):
        rendered = LLMPromptTemplate.render(
            _full_ctx(),
            safety_rules=SafetyValidator(list(DEFAULT_SAFETY_RULES)).describe_rules(_full_ctx()),
        )
        assert "이번 주" not in rendered
        assert "주간 " not in rendered
        assert "7일 계획 범위" in rendered

    def test_contains_scores(self, rendered):
        assert "회복도 68" in rendered
        assert "피로도 52" in rendered
        assert "부상 리스크 30" in rendered
        assert "활성 부상 severity 4" in rendered

    def test_contains_pace_capability_profile(self, rendered):
        assert "페이스 능력 프로파일" in rendered
        assert "safetyBands" in rendered
        assert "referenceCenters" in rendered
        assert "4:30" in rendered  # interval
        assert "6:45" in rendered  # base

    def test_does_not_force_copying_reference_paces(self, rendered):
        assert "targetValue 는 반드시 이 값 중 하나로 선택" not in rendered
        assert "반드시 PaceZones 값을 targetValue 에 사용" not in rendered
        assert "그대로 복사할 필요는 없습니다" in rendered

    def test_contains_execution_history_raw(self, rendered):
        assert "2026-04-19" in rendered
        assert "long_run" in rendered
        # raw 값 그대로 JSON 에 포함
        assert "18.2" in rendered

    def test_contains_active_injury(self, rendered):
        assert "right knee" in rendered
        assert "통증 지속" in rendered

    def test_contains_recent_feedback(self, rendered):
        assert '"fatigueScore": 6' in rendered
        assert '"stalenessDays": 2' in rendered

    def test_contains_race_goal(self, rendered):
        assert "Spring Half" in rendered
        assert "2026-05-17" in rendered

    def test_contains_training_block(self, rendered):
        assert '"phase": "build"' in rendered
        assert '"weeksUntilRace":' in rendered  # derived

    def test_contains_replan_reasons(self, rendered):
        assert "missed_key_workout" in rendered

    def test_contains_availability(self, rendered):
        assert '"maxDurationMinutes": 60' in rendered
        assert "요일별 가용성" in rendered

    def test_contains_long_run_allowed_dates(self, rendered):
        assert "세션 배치 하드 제약" in rendered
        assert "longRunAllowedDates" in rendered
        assert "Long Run MUST be placed on one of those dates" in rendered
        assert '"date": "2026-04-25"' in rendered

    def test_contains_training_background(self, rendered):
        assert '"totalRunCount": 512' in rendered

    def test_contains_all_safety_rules(self, rendered):
        for rule in SAFETY_RULES:
            assert rule in rendered

    def test_contains_decision_tasks(self, rendered):
        assert "결정 과제" in rendered
        assert "sevenDayVolumeTargetKm" in rendered
        assert "weekly_volume_target_km" not in rendered
        assert "sessionType" in rendered
        assert "workoutType" in rendered

    def test_contains_workout_catalog_contract(self, rendered):
        assert "훈련 카탈로그" in rendered
        assert "workout.workoutName 은 반드시 workoutType 과 정확히 같은 문자열" in rendered
        assert "Threshold/Tempo Run 은 continuous quality" in rendered
        assert "Interval step 을 쓰지 마세요" in rendered
        assert "단일 10분 이상 continuous Interval step 금지" in rendered

    def test_contains_description_contract(self, rendered):
        assert "코치 설명 작성 규칙" in rendered
        assert "오늘 이 훈련을 배치한 이유" in rendered
        assert "어떤 능력이 좋아지는지" in rendered
        assert "실행 중 지킬 포인트" in rendered
        assert "한 구절짜리 일반 설명" in rendered

    def test_contains_output_schema(self, rendered):
        assert "출력 스키마" in rendered
        schema_json = json.dumps(OUTPUT_SCHEMA, ensure_ascii=False, sort_keys=True)
        assert schema_json in rendered

    def test_ends_with_json_only_instruction(self, rendered):
        assert "Return ONLY valid JSON" in rendered


class TestDeterminism:
    def test_same_input_produces_same_output(self):
        a = LLMPromptTemplate.render(_full_ctx(), SAFETY_RULES)
        b = LLMPromptTemplate.render(_full_ctx(), SAFETY_RULES)
        assert a == b

    def test_pace_zones_serialized_with_sorted_keys(self, rendered):
        # sort_keys=True → base 가 cooldown 보다 먼저 나와야 함 (알파벳 순)
        zones_start = rendered.find('{"base"')
        assert zones_start != -1


class TestContextAsDict:
    def test_as_dict_contains_all_sections(self):
        d = LLMPromptTemplate.context_as_dict(_full_ctx())
        assert d["today"] == "2026-04-20"
        assert d["scores"]["readiness"] == 68
        assert d["paceZones"]["interval"] == "4:30"
        assert "paceCapability" in d
        assert "safetyBands" in d["paceCapability"]
        assert d["placementConstraints"]["longRunAllowedDates"][0]["date"] == "2026-04-25"
        assert d["planPolicy"]["maxLongRuns"] == 1
        assert d["planPolicy"]["maxHardSessions"] == 2
        assert d["workoutCatalog"]["Threshold"]["sessionType"] == "quality"
        assert len(d["executionHistory14d"]) == 1
        assert d["activeInjury"]["injuryArea"] == "right knee"
        assert len(d["recentFeedback"]) == 1
        assert d["trainingBlock"]["phase"] == "build"
        assert d["raceGoal"]["distance"] == "Half"
        assert d["replanReasons"] == ["missed_key_workout"]


class TestStrengthToggle:
    def test_include_strength_adds_section(self):
        ctx = _full_ctx()
        out = LLMPromptTemplate.render(ctx, safety_rules=["룰"], include_strength=True)
        assert "근력 훈련 참고" in out
        assert "근력 조언" in out

    def test_default_is_running_only(self):
        ctx = _full_ctx()
        out = LLMPromptTemplate.render(ctx, safety_rules=["룰"])
        assert "근력 세션을 넣지 마세요" in out


class TestMinimalContext:
    def test_renders_without_optional_fields(self):
        ctx = CoachingContext(
            today=date(2026, 4, 20),
            scores=CoachingScores(readiness=50, fatigue=50, injury_risk=20),
            pace_zones=ZONES,
        )
        out = LLMPromptTemplate.render(ctx, safety_rules=["단일 룰"])
        assert "2026-04-20" in out
        assert "단일 룰" in out
        # 옵션 필드 없음 → null/[] 직렬화
        assert "[활성 부상] {}" in out
        assert "[대회 컨텍스트] null" in out

    def test_does_not_emit_injury_severity_line_when_zero(self):
        ctx = CoachingContext(
            today=date(2026, 4, 20),
            scores=CoachingScores(readiness=70, fatigue=40, injury_risk=15),
            pace_zones=ZONES,
        )
        out = LLMPromptTemplate.render(ctx, safety_rules=[])
        assert "활성 부상 severity" not in out
