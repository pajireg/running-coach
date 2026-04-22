"""NoBackToBackQuality + NoQualityAfterLongRun + Quality48hSpacing."""

from __future__ import annotations

from running_coach.coaching.safety.rules import (
    NoBackToBackQuality,
    NoQualityAfterLongRun,
    Quality48hSpacing,
)

from .conftest import make_plan


class TestNoBackToBackQuality:
    def test_passes_with_spacing(self, healthy_ctx):
        plan = make_plan(["quality", "base", "recovery", "base", "quality", "base", "rest"])
        assert NoBackToBackQuality().check(plan, healthy_ctx) == []

    def test_detects_two_quality_in_a_row(self, healthy_ctx):
        plan = make_plan(["quality", "quality", "base", "base", "long_run", "base", "rest"])
        violations = NoBackToBackQuality().check(plan, healthy_ctx)
        assert [v.day_index for v in violations] == [1]

    def test_detects_quality_then_long_run(self, healthy_ctx):
        plan = make_plan(["base", "quality", "long_run", "base", "base", "base", "rest"])
        violations = NoBackToBackQuality().check(plan, healthy_ctx)
        assert [v.day_index for v in violations] == [1]

    def test_corrector_demotes_second_to_recovery(self, healthy_ctx):
        rule = NoBackToBackQuality()
        plan = make_plan(["quality", "quality", "base", "base", "long_run", "base", "rest"])
        violations = rule.check(plan, healthy_ctx)
        fixed = rule.correct(plan, healthy_ctx, violations)
        assert fixed.plan[1].session_type == "recovery"
        assert "회복주" in fixed.plan[1].workout.description
        assert "유산소 기반" in fixed.plan[1].workout.description
        assert rule.check(fixed, healthy_ctx) == []

    def test_corrector_preserves_long_run_when_quality_before_long_run(self, healthy_ctx):
        rule = NoBackToBackQuality()
        plan = make_plan(["base", "quality", "long_run", "base", "base", "base", "rest"])
        violations = rule.check(plan, healthy_ctx)
        fixed = rule.correct(plan, healthy_ctx, violations)
        assert fixed.plan[1].session_type == "recovery"
        assert fixed.plan[2].session_type == "long_run"
        assert rule.check(fixed, healthy_ctx) == []


class TestNoQualityAfterLongRun:
    def test_passes_without_long_run_quality_adjacency(self, healthy_ctx):
        plan = make_plan(["base", "quality", "base", "base", "long_run", "rest", "base"])
        assert NoQualityAfterLongRun().check(plan, healthy_ctx) == []

    def test_detects_quality_day_after_long_run(self, healthy_ctx):
        plan = make_plan(["base", "base", "base", "long_run", "quality", "base", "rest"])
        violations = NoQualityAfterLongRun().check(plan, healthy_ctx)
        assert [v.day_index for v in violations] == [4]

    def test_corrector_demotes_to_recovery(self, healthy_ctx):
        rule = NoQualityAfterLongRun()
        plan = make_plan(["base", "base", "base", "long_run", "quality", "base", "rest"])
        violations = rule.check(plan, healthy_ctx)
        fixed = rule.correct(plan, healthy_ctx, violations)
        assert fixed.plan[4].session_type == "recovery"
        assert rule.check(fixed, healthy_ctx) == []


class TestQuality48hSpacing:
    def test_passes_with_48h_gap(self, healthy_ctx):
        plan = make_plan(["quality", "base", "base", "quality", "base", "base", "rest"])
        assert Quality48hSpacing().check(plan, healthy_ctx) == []

    def test_detects_hard_sessions_on_adjacent_days(self, healthy_ctx):
        # adjacent day 도 잡힘 (NoBackToBackQuality 와 중복 커버)
        plan = make_plan(["quality", "quality", "base", "base", "long_run", "base", "rest"])
        violations = Quality48hSpacing().check(plan, healthy_ctx)
        assert [v.day_index for v in violations] == [1]

    def test_corrector_demotes_second_hard_session(self, healthy_ctx):
        rule = Quality48hSpacing()
        plan = make_plan(["quality", "quality", "base", "base", "long_run", "base", "rest"])
        violations = rule.check(plan, healthy_ctx)
        fixed = rule.correct(plan, healthy_ctx, violations)
        assert fixed.plan[1].session_type == "recovery"
        assert rule.check(fixed, healthy_ctx) == []

    def test_corrector_preserves_long_run_when_quality_before_long_run(self, healthy_ctx):
        rule = Quality48hSpacing()
        plan = make_plan(["base", "quality", "long_run", "base", "base", "base", "rest"])
        violations = rule.check(plan, healthy_ctx)
        assert [v.day_index for v in violations] == [1]
        fixed = rule.correct(plan, healthy_ctx, violations)
        assert fixed.plan[1].session_type == "recovery"
        assert fixed.plan[2].session_type == "long_run"
        assert rule.check(fixed, healthy_ctx) == []
