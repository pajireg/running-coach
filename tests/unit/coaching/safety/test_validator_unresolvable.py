"""SafetyValidator 수렴 실패 시 동작."""

from __future__ import annotations

from running_coach.coaching.safety import SafetyValidator, Violation
from running_coach.coaching.safety.rules import Severity

from .conftest import make_plan


class NeverSettlesRule:
    """매 패스마다 동일 violation 을 계속 반환하는 룰 (수렴 실패 유도)."""

    rule_id = "never_settles"
    severity: Severity = "block"

    def __init__(self):
        self.call_count = 0

    def check(self, plan, ctx):
        self.call_count += 1
        return [
            Violation(
                rule_id=self.rule_id,
                severity=self.severity,
                message="deliberately unresolvable",
                day_index=0,
            )
        ]

    def correct(self, plan, ctx, violations):
        # no-op: 위반을 고치지 못함
        return plan

    def describe(self, ctx):
        return "test rule that never settles"


class TestUnresolvable:
    def test_identical_violations_trigger_loop_detection(self, healthy_ctx):
        """동일 identity 가 반복되면 unresolvable 로 마킹."""
        rule = NeverSettlesRule()
        validator = SafetyValidator(rules=[rule], max_passes=5)
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        result = validator.validate(plan, healthy_ctx)
        assert result.unresolvable is True
        # 루프 감지로 max_passes 보다 일찍 중단
        assert rule.call_count < 5

    def test_unresolvable_returns_best_effort_plan(self, healthy_ctx):
        """수렴 실패해도 plan 은 유효한 객체를 반환."""
        rule = NeverSettlesRule()
        validator = SafetyValidator(rules=[rule])
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        result = validator.validate(plan, healthy_ctx)
        assert result.plan is not None
        assert len(result.plan.plan) == 7

    def test_unresolvable_records_violations(self, healthy_ctx):
        rule = NeverSettlesRule()
        validator = SafetyValidator(rules=[rule])
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        result = validator.validate(plan, healthy_ctx)
        assert len(result.violations) >= 1
        assert all(v.rule_id == "never_settles" for v in result.violations)


class TestMaxPassesExhaustion:
    """수렴 실패가 identity loop 이 아닌 max_passes 소진으로 발생하는 경우."""

    def test_rule_that_eventually_settles(self, healthy_ctx):
        """매 패스마다 다른 violation 을 내다가 결국 수렴."""

        class EventuallySettlesRule:
            rule_id = "eventually_settles"
            severity: Severity = "block"

            def __init__(self):
                self.remaining = 2

            def check(self, plan, ctx):
                if self.remaining <= 0:
                    return []
                return [
                    Violation(
                        rule_id=self.rule_id,
                        severity=self.severity,
                        message=f"iteration {self.remaining}",
                        day_index=self.remaining,  # 매번 다른 day_index
                    )
                ]

            def correct(self, plan, ctx, violations):
                self.remaining -= 1
                return plan

            def describe(self, ctx):
                return "settles eventually"

        rule = EventuallySettlesRule()
        validator = SafetyValidator(rules=[rule], max_passes=5)
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        result = validator.validate(plan, healthy_ctx)
        assert not result.unresolvable
        assert rule.remaining == 0
