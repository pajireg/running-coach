"""MaxOneLongRun + WeeklyHardCap + MinOneRestPerWeek."""

from __future__ import annotations

from running_coach.coaching.safety.rules import (
    MaxOneLongRun,
    MinOneRestPerWeek,
    WeeklyHardCap,
)

from .conftest import make_plan


class TestMaxOneLongRun:
    def test_passes_with_one_long_run(self, healthy_ctx):
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        assert MaxOneLongRun().check(plan, healthy_ctx) == []

    def test_detects_two_long_runs(self, healthy_ctx):
        plan = make_plan(["base", "long_run", "base", "base", "base", "long_run", "rest"])
        violations = MaxOneLongRun().check(plan, healthy_ctx)
        assert [v.day_index for v in violations] == [5]  # 두 번째만

    def test_corrector_demotes_second_to_base(self, healthy_ctx):
        rule = MaxOneLongRun()
        plan = make_plan(["base", "long_run", "base", "base", "base", "long_run", "rest"])
        violations = rule.check(plan, healthy_ctx)
        fixed = rule.correct(plan, healthy_ctx, violations)
        assert fixed.plan[1].session_type == "long_run"  # 첫 번째 유지
        assert fixed.plan[5].session_type == "base"
        assert rule.check(fixed, healthy_ctx) == []


class TestWeeklyHardCap:
    def test_passes_with_two_hard_sessions(self, healthy_ctx):
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        assert WeeklyHardCap().check(plan, healthy_ctx) == []

    def test_detects_three_hard_sessions(self, healthy_ctx):
        plan = make_plan(["quality", "base", "quality", "base", "base", "long_run", "rest"])
        violations = WeeklyHardCap().check(plan, healthy_ctx)
        assert [v.day_index for v in violations] == [5]  # 3rd = long_run

    def test_corrector_demotes_third_to_base(self, healthy_ctx):
        rule = WeeklyHardCap()
        plan = make_plan(["quality", "base", "quality", "base", "base", "long_run", "rest"])
        violations = rule.check(plan, healthy_ctx)
        fixed = rule.correct(plan, healthy_ctx, violations)
        assert fixed.plan[5].session_type == "base"
        assert rule.check(fixed, healthy_ctx) == []


class TestMinOneRestPerWeek:
    def test_passes_with_one_rest(self, healthy_ctx):
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        assert MinOneRestPerWeek().check(plan, healthy_ctx) == []

    def test_detects_no_rest(self, healthy_ctx):
        plan = make_plan(["base", "quality", "base", "recovery", "base", "long_run", "base"])
        violations = MinOneRestPerWeek().check(plan, healthy_ctx)
        assert len(violations) == 1
        assert violations[0].day_index is None

    def test_corrector_converts_base_far_from_long_run(self, healthy_ctx):
        rule = MinOneRestPerWeek()
        # long_run on day 5; base days at 0,2,4,6; furthest from long_run=0
        plan = make_plan(["base", "quality", "base", "recovery", "base", "long_run", "base"])
        violations = rule.check(plan, healthy_ctx)
        fixed = rule.correct(plan, healthy_ctx, violations)
        rest_days = [i for i, d in enumerate(fixed.plan) if d.session_type == "rest"]
        assert len(rest_days) == 1
        # day 0 (distance 5) 이 day 6 (distance 1) 보다 long_run 에서 더 멂
        assert rest_days[0] == 0
        assert rule.check(fixed, healthy_ctx) == []
