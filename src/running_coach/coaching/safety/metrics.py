"""안전 룰 위반 메트릭 emitter.

실제 metrics backend 연결은 추후. 현재는 logger 기반 placeholder.
카운터 레이블 cardinality 가 폭발하지 않도록 rule_id / severity 만 라벨로 허용.
"""

from __future__ import annotations

from typing import Literal

from ...utils.logger import get_logger

logger = get_logger(__name__)


Severity = Literal["warn", "block"]


def emit_safety_violation(rule_id: str, severity: Severity, detail: str = "") -> None:
    """위반 1건 기록. rule_id 는 열거형 상수 (13종)."""
    logger.warning(
        "[safety] rule_id=%s severity=%s %s",
        rule_id,
        severity,
        detail,
    )


def emit_safety_unresolvable(rule_ids: list[str]) -> None:
    """max_passes 초과로 수렴 실패한 경우."""
    logger.error(
        "[safety] unresolvable rules=%s",
        ",".join(sorted(set(rule_ids))),
    )
