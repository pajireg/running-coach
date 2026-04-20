"""AcwrCap: 주간 볼륨이 chronic_ewma_load × 1.5 초과 시 duration 스케일 다운."""

from __future__ import annotations

from datetime import date

from running_coach.coaching.context import (
    AvailabilitySlot,
    CoachingContext,
    CoachingScores,
)
from running_coach.coaching.safety.rules import AcwrCap

from .conftest import DEFAULT_ZONES, make_plan


def _ctx_with_chronic(chronic_km: float) -> CoachingContext:
    return CoachingContext(
        today=date(2026, 4, 20),
        scores=CoachingScores(
            readiness=70,
            fatigue=40,
            injury_risk=20,
            active_injury_severity=0,
            chronic_ewma_load=chronic_km,
        ),
        pace_zones=DEFAULT_ZONES,
        availability={i: AvailabilitySlot(weekday=i, is_available=True) for i in range(7)},
    )


class TestAcwrCap:
    def test_passes_when_no_chronic_baseline(self):
        ctx = _ctx_with_chronic(0.0)
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        # chronic 0 이면 비활성
        assert AcwrCap().check(plan, ctx) == []

    def test_passes_when_ratio_below_cap(self):
        # 기본 plan 총 km 계산: 대략 base_pace(405s) 기준.
        # 합산 duration: base(2700)*4 + quality(2220) + long_run(4500) + rest(0) ≈ 17520s
        # 17520 / 405 ≈ 43km. chronic 40 이면 ratio ≈ 1.08
        ctx = _ctx_with_chronic(40.0)
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        assert AcwrCap().check(plan, ctx) == []

    def test_detects_high_ratio(self):
        # chronic 10km 이면 ratio 약 4.3 > 1.5
        ctx = _ctx_with_chronic(10.0)
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        violations = AcwrCap().check(plan, ctx)
        assert len(violations) == 1

    def test_corrector_scales_durations_to_target(self):
        rule = AcwrCap()
        ctx = _ctx_with_chronic(10.0)
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        violations = rule.check(plan, ctx)
        fixed = rule.correct(plan, ctx, violations)
        # 수정 후 ratio ≤ 1.5
        assert rule.check(fixed, ctx) == []

    def test_corrector_preserves_long_run_and_quality(self):
        """극단적 ACWR 이면 structural 축소(한 날을 rest 로)도 허용되지만
        long_run / quality 는 유지한다."""
        rule = AcwrCap()
        ctx = _ctx_with_chronic(10.0)
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        violations = rule.check(plan, ctx)
        fixed = rule.correct(plan, ctx, violations)
        types = [d.session_type for d in fixed.plan]
        assert types.count("long_run") == 1
        assert types.count("quality") == 1

    def test_corrector_structurally_reduces_for_extreme_ratio(self):
        """chronic 이 매우 작을 때 base/recovery 를 rest 로 구조적 축소."""
        rule = AcwrCap()
        ctx = _ctx_with_chronic(3.0)  # ratio > 10배
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        original_rest = sum(1 for d in plan.plan if d.session_type == "rest")
        violations = rule.check(plan, ctx)
        fixed = rule.correct(plan, ctx, violations)
        new_rest = sum(1 for d in fixed.plan if d.session_type == "rest")
        assert new_rest > original_rest
        # 최종 위반도 해결
        assert rule.check(fixed, ctx) == []
