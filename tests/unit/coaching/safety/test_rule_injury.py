"""InjuryBlockQuality + InjuryReduceVolume."""

from __future__ import annotations

from running_coach.coaching.safety.rules import (
    InjuryBlockQuality,
    InjuryReduceVolume,
)

from .conftest import make_plan


class TestInjuryBlockQuality:
    def test_no_violations_without_severe_injury(self, healthy_ctx):
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        assert InjuryBlockQuality().check(plan, healthy_ctx) == []

    def test_detects_quality_with_severe_injury(self, injured_ctx):
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        violations = InjuryBlockQuality().check(plan, injured_ctx)
        assert len(violations) == 1
        assert violations[0].day_index == 1

    def test_corrector_demotes_quality_to_recovery(self, injured_ctx):
        rule = InjuryBlockQuality()
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        violations = rule.check(plan, injured_ctx)
        fixed = rule.correct(plan, injured_ctx, violations)
        assert fixed.plan[1].session_type == "recovery"
        # 재검증 시 위반 없음
        assert rule.check(fixed, injured_ctx) == []

    def test_volume_reduced_on_corrected_day(self, injured_ctx):
        rule = InjuryBlockQuality()
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        original_minutes = plan.plan[1].workout.total_duration_minutes
        violations = rule.check(plan, injured_ctx)
        fixed = rule.correct(plan, injured_ctx, violations)
        assert fixed.plan[1].workout.total_duration_minutes < original_minutes


class TestInjuryReduceVolume:
    def test_no_violations_without_moderate_injury(self, healthy_ctx):
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        assert InjuryReduceVolume().check(plan, healthy_ctx) == []

    def test_not_triggered_by_severe_injury(self, injured_ctx):
        # severe (≥6) 는 InjuryBlockQuality 영역; InjuryReduceVolume 은 3-5 만
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        assert InjuryReduceVolume().check(plan, injured_ctx) == []

    def test_converts_intervals_to_run(self, mildly_injured_ctx):
        rule = InjuryReduceVolume()
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        assert any(s.type == "Interval" for s in plan.plan[1].workout.steps)
        violations = rule.check(plan, mildly_injured_ctx)
        assert len(violations) == 1
        fixed = rule.correct(plan, mildly_injured_ctx, violations)
        assert not any(s.type == "Interval" for s in fixed.plan[1].workout.steps)
        assert rule.check(fixed, mildly_injured_ctx) == []
