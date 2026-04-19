"""SafetyValidator: 룰 실행 + auto-correct + 루프 감지."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...utils.logger import get_logger
from .metrics import emit_safety_unresolvable, emit_safety_violation
from .rules import SafetyRule, Violation

if TYPE_CHECKING:
    from ...models.training import TrainingPlan
    from ..context import CoachingContext


logger = get_logger(__name__)


@dataclass
class ValidationResult:
    """validator 결과."""

    plan: "TrainingPlan"
    violations: list[Violation]
    unresolvable: bool = False


class SafetyValidator:
    """안전 룰 다중 패스 검증·보정.

    - 패스마다 모든 룰 실행 → 위반 발견 시 룰의 correct() 호출 → 재실행
    - max_passes 내 수렴 실패 시 best-effort plan + unresolvable=True
    - 루프 감지: 동일 패스에서 같은 (rule_id, day_index) 가 다시 나오면 unresolvable
    """

    def __init__(self, rules: list[SafetyRule], max_passes: int = 3):
        self._rules = rules
        self._max_passes = max_passes

    def validate(
        self,
        plan: "TrainingPlan",
        ctx: "CoachingContext",
    ) -> ValidationResult:
        """plan 을 룰에 통과시키고 필요 시 보정. 모든 위반은 메트릭으로 emit."""
        all_violations: list[Violation] = []
        seen_per_pass: list[set[tuple[str, int | None]]] = []

        current_plan = plan
        unresolvable = False
        for pass_num in range(self._max_passes):
            pass_violations: list[Violation] = []
            for rule in self._rules:
                pass_violations.extend(rule.check(current_plan, ctx))

            if not pass_violations:
                break

            pass_identities = {v.identity for v in pass_violations}
            # 루프 감지: 이전 패스와 identity 가 완전히 동일하면 수렴 실패
            if seen_per_pass and pass_identities == seen_per_pass[-1]:
                unresolvable = True
                all_violations.extend(pass_violations)
                for v in pass_violations:
                    emit_safety_violation(v.rule_id, v.severity, v.message)
                break
            seen_per_pass.append(pass_identities)

            for v in pass_violations:
                emit_safety_violation(v.rule_id, v.severity, v.message)
            all_violations.extend(pass_violations)

            # 룰별로 해당 룰의 위반들을 묶어서 correct()
            by_rule: dict[str, list[Violation]] = {}
            for v in pass_violations:
                by_rule.setdefault(v.rule_id, []).append(v)
            for rule in self._rules:
                rule_violations = by_rule.get(rule.rule_id)
                if rule_violations:
                    current_plan = rule.correct(current_plan, ctx, rule_violations)
        else:
            # for 루프가 break 없이 끝남 = max_passes 모두 소진
            final_check: list[Violation] = []
            for rule in self._rules:
                final_check.extend(rule.check(current_plan, ctx))
            if final_check:
                unresolvable = True
                all_violations.extend(final_check)

        if unresolvable:
            emit_safety_unresolvable([v.rule_id for v in all_violations])

        return ValidationResult(
            plan=current_plan,
            violations=all_violations,
            unresolvable=unresolvable,
        )

    def describe_rules(self, ctx: "CoachingContext") -> list[str]:
        """프롬프트용 룰 요약 (LLM 이 사전에 회피할 수 있도록)."""
        return [rule.describe(ctx) for rule in self._rules]
