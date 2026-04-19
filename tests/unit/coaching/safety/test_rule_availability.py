"""RespectUnavailability + MaxDurationPerDay."""

from __future__ import annotations

from datetime import date

from running_coach.coaching.context import (
    AvailabilitySlot,
    CoachingContext,
    CoachingScores,
)
from running_coach.coaching.safety.rules import (
    MaxDurationPerDay,
    RespectUnavailability,
)

from .conftest import DEFAULT_ZONES, make_plan


def _ctx_with_availability(slots: dict[int, AvailabilitySlot]) -> CoachingContext:
    return CoachingContext(
        today=date(2026, 4, 20),
        scores=CoachingScores(
            readiness=70,
            fatigue=40,
            injury_risk=20,
            active_injury_severity=0,
            chronic_ewma_load=50.0,
        ),
        pace_zones=DEFAULT_ZONES,
        availability=slots,
    )


class TestRespectUnavailability:
    def test_passes_when_rest_on_unavailable_day(self):
        # 월요일 (weekday=0) 불가
        availability = {
            0: AvailabilitySlot(weekday=0, is_available=False),
            **{i: AvailabilitySlot(weekday=i, is_available=True) for i in range(1, 7)},
        }
        ctx = _ctx_with_availability(availability)
        plan = make_plan(["rest", "quality", "base", "base", "base", "long_run", "base"])
        assert RespectUnavailability().check(plan, ctx) == []

    def test_detects_non_rest_on_unavailable_day(self):
        availability = {
            0: AvailabilitySlot(weekday=0, is_available=False),
            **{i: AvailabilitySlot(weekday=i, is_available=True) for i in range(1, 7)},
        }
        ctx = _ctx_with_availability(availability)
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        violations = RespectUnavailability().check(plan, ctx)
        assert [v.day_index for v in violations] == [0]

    def test_corrector_forces_rest(self):
        rule = RespectUnavailability()
        availability = {
            0: AvailabilitySlot(weekday=0, is_available=False),
            **{i: AvailabilitySlot(weekday=i, is_available=True) for i in range(1, 7)},
        }
        ctx = _ctx_with_availability(availability)
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        violations = rule.check(plan, ctx)
        fixed = rule.correct(plan, ctx, violations)
        assert fixed.plan[0].session_type == "rest"
        assert rule.check(fixed, ctx) == []


class TestMaxDurationPerDay:
    def test_passes_when_within_cap(self):
        availability = {
            i: AvailabilitySlot(weekday=i, is_available=True, max_duration_minutes=120)
            for i in range(7)
        }
        ctx = _ctx_with_availability(availability)
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        assert MaxDurationPerDay().check(plan, ctx) == []

    def test_detects_over_cap(self):
        # long_run 기본 4500s = 75m; cap 을 30m 로 설정
        availability = {
            i: AvailabilitySlot(weekday=i, is_available=True, max_duration_minutes=30)
            for i in range(7)
        }
        ctx = _ctx_with_availability(availability)
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        violations = MaxDurationPerDay().check(plan, ctx)
        # quality, long_run, base(≥45m) 전부 위반
        assert len(violations) >= 3

    def test_corrector_truncates_proportionally(self):
        rule = MaxDurationPerDay()
        availability = {
            i: AvailabilitySlot(weekday=i, is_available=True, max_duration_minutes=30)
            for i in range(7)
        }
        ctx = _ctx_with_availability(availability)
        plan = make_plan(["base", "base", "base", "base", "base", "base", "rest"])
        violations = rule.check(plan, ctx)
        fixed = rule.correct(plan, ctx, violations)
        for day in fixed.plan:
            if day.session_type == "rest":
                continue
            assert day.workout.total_duration_minutes <= 30
        assert rule.check(fixed, ctx) == []
