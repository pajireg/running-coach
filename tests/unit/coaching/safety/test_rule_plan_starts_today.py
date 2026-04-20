"""PlanStartsToday: LLM 이 엉뚱한 시작일을 내놓으면 오늘 기준으로 rebase."""

from __future__ import annotations

from datetime import date, timedelta

from running_coach.coaching.safety.rules import PlanStartsToday

from .conftest import make_plan


class TestPlanStartsToday:
    def test_passes_when_starts_today(self, healthy_ctx):
        plan = make_plan(
            ["base", "quality", "base", "base", "base", "long_run", "rest"],
            start=healthy_ctx.today,
        )
        assert PlanStartsToday().check(plan, healthy_ctx) == []

    def test_detects_wrong_start_date(self, healthy_ctx):
        wrong_start = healthy_ctx.today + timedelta(days=2)
        plan = make_plan(
            ["base", "quality", "base", "base", "base", "long_run", "rest"],
            start=wrong_start,
        )
        violations = PlanStartsToday().check(plan, healthy_ctx)
        assert len(violations) == 1

    def test_corrector_rebases_all_dates(self, healthy_ctx):
        rule = PlanStartsToday()
        wrong_start = healthy_ctx.today + timedelta(days=2)
        plan = make_plan(
            ["base", "quality", "base", "base", "base", "long_run", "rest"],
            start=wrong_start,
        )
        violations = rule.check(plan, healthy_ctx)
        fixed = rule.correct(plan, healthy_ctx, violations)
        expected = [healthy_ctx.today + timedelta(days=i) for i in range(7)]
        assert [d.date for d in fixed.plan] == expected
        assert rule.check(fixed, healthy_ctx) == []

    def test_corrector_preserves_session_types(self, healthy_ctx):
        rule = PlanStartsToday()
        types = ["base", "quality", "base", "recovery", "base", "long_run", "rest"]
        wrong_start = healthy_ctx.today - timedelta(days=5)
        plan = make_plan(types, start=wrong_start)
        violations = rule.check(plan, healthy_ctx)
        fixed = rule.correct(plan, healthy_ctx, violations)
        assert [d.session_type for d in fixed.plan] == types

    def test_also_catches_past_start(self, healthy_ctx):
        rule = PlanStartsToday()
        past_start = healthy_ctx.today - timedelta(days=10)
        plan = make_plan(["base"] * 6 + ["rest"], start=past_start)
        violations = rule.check(plan, healthy_ctx)
        assert len(violations) == 1
        fixed = rule.correct(plan, healthy_ctx, violations)
        assert fixed.plan[0].date == healthy_ctx.today


def _unused_start_not_today(healthy_ctx) -> date:
    return healthy_ctx.today + timedelta(days=3)
