"""LegacySkeletonPlanner: 기존 TrainingPlanner 를 Planner 프로토콜로 wrap.

planner.py 본문 로직은 건드리지 않는다. PR7 에서 제거 예정.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, cast

from ...models.config import RaceConfig
from ...models.metrics import AdvancedMetrics
from ...models.training import TrainingPlan

if TYPE_CHECKING:
    from ...clients.gemini.planner import TrainingPlanner


class LegacySkeletonPlanner:
    """기존 skeleton 기반 planner 의 slim wrapper.

    replan_reasons 는 무시됨 (legacy 는 사용하지 않음).
    """

    def __init__(self, inner: "TrainingPlanner"):
        self._inner = inner

    def generate_plan(
        self,
        metrics: AdvancedMetrics,
        race_config: RaceConfig,
        include_strength: bool = False,
        training_background: Optional[dict[str, Any]] = None,
        replan_reasons: Optional[list[str]] = None,  # noqa: ARG002 — legacy 는 미사용
    ) -> Optional[TrainingPlan]:
        return cast(
            Optional[TrainingPlan],
            self._inner.generate_plan(
                metrics,
                race_config,
                include_strength=include_strength,
                training_background=training_background,
            ),
        )
