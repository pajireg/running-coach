"""LongRunCap + HardSessionCap + MinRestDays."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from running_coach.coaching.context import PlanPolicy
from running_coach.coaching.safety.rules import (
    HardSessionCap,
    LongRunCap,
    MinRestDays,
    PreferLongRunAvailability,
)

from .conftest import make_plan


def _weekend_long_run_ctx(healthy_ctx):
    return replace(
        healthy_ctx,
        availability={
            **healthy_ctx.availability,
            5: replace(
                healthy_ctx.availability[5],
                max_duration_minutes=90,
                preferred_session_type="long_run",
            ),
            6: replace(
                healthy_ctx.availability[6],
                max_duration_minutes=90,
                preferred_session_type="long_run",
            ),
        },
    )


class TestLongRunCap:
    def test_passes_with_one_long_run(self, healthy_ctx):
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        assert LongRunCap().check(plan, healthy_ctx) == []

    def test_detects_two_long_runs(self, healthy_ctx):
        plan = make_plan(["base", "long_run", "base", "base", "base", "long_run", "rest"])
        violations = LongRunCap().check(plan, healthy_ctx)
        assert [v.day_index for v in violations] == [5]  # 두 번째만

    def test_corrector_demotes_second_to_base(self, healthy_ctx):
        rule = LongRunCap()
        plan = make_plan(["base", "long_run", "base", "base", "base", "long_run", "rest"])
        violations = rule.check(plan, healthy_ctx)
        fixed = rule.correct(plan, healthy_ctx, violations)
        assert fixed.plan[1].session_type == "long_run"  # 첫 번째 유지
        assert fixed.plan[5].session_type == "base"
        assert rule.check(fixed, healthy_ctx) == []

    def test_policy_can_allow_two_long_runs(self, healthy_ctx):
        ctx = replace(healthy_ctx, plan_policy=PlanPolicy(max_long_runs=2))
        plan = make_plan(["base", "long_run", "base", "base", "base", "long_run", "rest"])
        assert LongRunCap().check(plan, ctx) == []
        assert "최대 2회" in LongRunCap().describe(ctx)


class TestPreferLongRunAvailability:
    def test_passes_when_long_run_on_preferred_weekend(self, healthy_ctx):
        ctx = _weekend_long_run_ctx(healthy_ctx)
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        assert PreferLongRunAvailability().check(plan, ctx) == []

    def test_detects_weekday_long_run_when_weekend_preferred(self, healthy_ctx):
        ctx = _weekend_long_run_ctx(healthy_ctx)
        plan = make_plan(["base", "quality", "long_run", "base", "base", "recovery", "rest"])
        violations = PreferLongRunAvailability().check(plan, ctx)
        assert [v.day_index for v in violations] == [2]

    def test_corrector_moves_long_run_to_preferred_weekend(self, healthy_ctx):
        ctx = _weekend_long_run_ctx(healthy_ctx)
        rule = PreferLongRunAvailability()
        plan = make_plan(
            ["rest", "base", "quality", "recovery", "rest", "long_run", "base"],
            start=healthy_ctx.today + timedelta(days=3),
        )

        fixed = rule.correct(plan, ctx, rule.check(plan, ctx))

        assert fixed.plan[2].date.weekday() == 5
        assert fixed.plan[2].session_type == "long_run"
        assert fixed.plan[5].session_type == "quality"
        assert rule.check(fixed, ctx) == []


class TestHardSessionCap:
    def test_passes_with_two_hard_sessions(self, healthy_ctx):
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        assert HardSessionCap().check(plan, healthy_ctx) == []

    def test_detects_three_hard_sessions(self, healthy_ctx):
        plan = make_plan(["quality", "base", "quality", "base", "base", "long_run", "rest"])
        violations = HardSessionCap().check(plan, healthy_ctx)
        assert [v.day_index for v in violations] == [5]  # 3rd = long_run

    def test_corrector_demotes_third_to_base(self, healthy_ctx):
        rule = HardSessionCap()
        plan = make_plan(["quality", "base", "quality", "base", "base", "long_run", "rest"])
        violations = rule.check(plan, healthy_ctx)
        fixed = rule.correct(plan, healthy_ctx, violations)
        assert fixed.plan[5].session_type == "base"
        assert rule.check(fixed, healthy_ctx) == []

    def test_policy_can_allow_three_hard_sessions(self, healthy_ctx):
        ctx = replace(healthy_ctx, plan_policy=PlanPolicy(max_hard_sessions=3))
        plan = make_plan(["quality", "base", "quality", "base", "base", "long_run", "rest"])
        assert HardSessionCap().check(plan, ctx) == []
        assert "최대 3회" in HardSessionCap().describe(ctx)


class TestMinRestDays:
    def test_passes_with_one_rest(self, healthy_ctx):
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        assert MinRestDays().check(plan, healthy_ctx) == []

    def test_detects_no_rest(self, healthy_ctx):
        plan = make_plan(["base", "quality", "base", "recovery", "base", "long_run", "base"])
        violations = MinRestDays().check(plan, healthy_ctx)
        assert len(violations) == 1
        assert violations[0].day_index is None

    def test_corrector_converts_base_far_from_long_run(self, healthy_ctx):
        rule = MinRestDays()
        # long_run on day 5; base days at 0,2,4,6; furthest from long_run=0
        plan = make_plan(["base", "quality", "base", "recovery", "base", "long_run", "base"])
        violations = rule.check(plan, healthy_ctx)
        fixed = rule.correct(plan, healthy_ctx, violations)
        rest_days = [i for i, d in enumerate(fixed.plan) if d.session_type == "rest"]
        assert len(rest_days) == 1
        # day 0 (distance 5) 이 day 6 (distance 1) 보다 long_run 에서 더 멂
        assert rest_days[0] == 0
        assert rule.check(fixed, healthy_ctx) == []

    def test_policy_can_require_two_rest_days(self, healthy_ctx):
        ctx = replace(healthy_ctx, plan_policy=PlanPolicy(min_rest_days=2))
        rule = MinRestDays()
        plan = make_plan(["base", "quality", "base", "recovery", "base", "long_run", "rest"])
        fixed = rule.correct(plan, ctx, rule.check(plan, ctx))
        rest_days = [i for i, d in enumerate(fixed.plan) if d.session_type == "rest"]
        assert len(rest_days) == 2
        assert rule.check(fixed, ctx) == []
        assert "최소 2일" in rule.describe(ctx)
