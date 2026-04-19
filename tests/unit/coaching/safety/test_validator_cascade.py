"""SafetyValidator 다중 패스·룰 상호작용 테스트."""

from __future__ import annotations

from running_coach.coaching.safety import DEFAULT_SAFETY_RULES, SafetyValidator

from .conftest import make_plan


class TestValidatorEndToEnd:
    def test_healthy_plan_passes_through_unchanged(self, healthy_ctx):
        validator = SafetyValidator(rules=DEFAULT_SAFETY_RULES)
        plan = make_plan(["base", "quality", "base", "recovery", "base", "long_run", "rest"])
        result = validator.validate(plan, healthy_ctx)
        assert not result.unresolvable
        assert result.violations == []
        assert [d.session_type for d in result.plan.plan] == [
            "base",
            "quality",
            "base",
            "recovery",
            "base",
            "long_run",
            "rest",
        ]

    def test_violations_recorded_and_corrected(self, healthy_ctx):
        validator = SafetyValidator(rules=DEFAULT_SAFETY_RULES)
        # 연속 quality + rest 없음: 두 개 룰 동시 트리거
        plan = make_plan(["quality", "quality", "base", "base", "base", "long_run", "base"])
        result = validator.validate(plan, healthy_ctx)
        # 결국 안전한 plan 으로 수렴
        assert not result.unresolvable
        # 최종 plan 에 재검증 시 위반 없음
        for rule in DEFAULT_SAFETY_RULES:
            assert rule.check(result.plan, healthy_ctx) == []
        # 위반 기록은 남음
        assert len(result.violations) >= 1

    def test_cascade_injury_then_other_rules(self, injured_ctx):
        validator = SafetyValidator(rules=DEFAULT_SAFETY_RULES)
        # severe injury + quality 2개 + rest 없음
        plan = make_plan(["quality", "quality", "base", "base", "base", "long_run", "base"])
        result = validator.validate(plan, injured_ctx)
        # 수렴 성공
        assert not result.unresolvable
        # quality 가 전부 없어져야 함 (injury severity 6)
        assert not any(d.session_type == "quality" for d in result.plan.plan)
        # rest 가 최소 1일 있어야 함
        assert sum(1 for d in result.plan.plan if d.session_type == "rest") >= 1

    def test_multiple_passes_recorded_as_violations(self, healthy_ctx):
        """여러 패스에 걸쳐 해결되는 plan 도 최종적으로 수렴."""
        validator = SafetyValidator(rules=DEFAULT_SAFETY_RULES, max_passes=3)
        plan = make_plan(["quality", "long_run", "quality", "long_run", "base", "base", "base"])
        result = validator.validate(plan, healthy_ctx)
        assert not result.unresolvable
        # 주간 hard ≤ 2
        hard_count = sum(1 for d in result.plan.plan if d.session_type in ("quality", "long_run"))
        assert hard_count <= 2
        # long_run ≤ 1
        long_count = sum(1 for d in result.plan.plan if d.session_type == "long_run")
        assert long_count <= 1


class TestRuleSpecificInteraction:
    def test_quality_removed_then_rest_injected(self, injured_ctx):
        """severe injury → quality 전환 후에도 rest 부족하면 MinOneRestPerWeek 가 마무리."""
        validator = SafetyValidator(rules=DEFAULT_SAFETY_RULES)
        plan = make_plan(["quality", "base", "base", "base", "base", "long_run", "base"])
        result = validator.validate(plan, injured_ctx)
        assert not result.unresolvable
        assert sum(1 for d in result.plan.plan if d.session_type == "rest") >= 1
        assert not any(d.session_type == "quality" for d in result.plan.plan)

    def test_describe_rules_returns_korean_strings(self, healthy_ctx):
        validator = SafetyValidator(rules=DEFAULT_SAFETY_RULES)
        descriptions = validator.describe_rules(healthy_ctx)
        assert len(descriptions) == len(DEFAULT_SAFETY_RULES)
        assert all(isinstance(d, str) and d for d in descriptions)
