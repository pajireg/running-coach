"""안전 룰 위반 메트릭 emitter + 인-프로세스 카운터.

실제 Prometheus/OTLP 연동은 PR5 이후. 지금은 logger + 단순 카운터로
테스트·디버깅을 돕는다. 카운터 레이블 cardinality 는 rule_id / severity / mode
만 허용 (bounded).
"""

from __future__ import annotations

from collections import Counter
from typing import Literal

from ...utils.logger import get_logger

logger = get_logger(__name__)


Severity = Literal["warn", "block"]


# module-level counters — 테스트 편의용. 실 배포 시 Prom exporter 로 교체.
violation_counter: Counter[tuple[str, Severity]] = Counter()
unresolvable_counter: Counter[tuple[str, ...]] = Counter()
plan_generated_counter: Counter[str] = Counter()


def emit_safety_violation(rule_id: str, severity: Severity, detail: str = "") -> None:
    """위반 1건 기록."""
    violation_counter[(rule_id, severity)] += 1
    logger.warning(
        "[safety] rule_id=%s severity=%s %s",
        rule_id,
        severity,
        detail,
    )


def emit_safety_unresolvable(rule_ids: list[str]) -> None:
    """max_passes 초과로 수렴 실패."""
    key = tuple(sorted(set(rule_ids)))
    unresolvable_counter[key] += 1
    logger.error(
        "[safety] unresolvable rules=%s",
        ",".join(key),
    )


def emit_plan_generated(
    mode: str,
    violation_count: int,
    unresolvable: bool,
) -> None:
    """계획 1건 생성 완료 기록."""
    plan_generated_counter[mode] += 1
    logger.info(
        "[coaching.plan.generated] mode=%s violations=%d unresolvable=%s",
        mode,
        violation_count,
        unresolvable,
    )


def reset_counters_for_test() -> None:
    """테스트 픽스처 용 - 모든 모듈 카운터 초기화."""
    violation_counter.clear()
    unresolvable_counter.clear()
    plan_generated_counter.clear()
