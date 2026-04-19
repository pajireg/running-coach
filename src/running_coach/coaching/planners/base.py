"""Planner 인터페이스."""

from __future__ import annotations

from typing import Any, Optional, Protocol

from ...models.config import RaceConfig
from ...models.metrics import AdvancedMetrics
from ...models.training import TrainingPlan


class Planner(Protocol):
    """legacy / llm_driven 공용 인터페이스.

    replan_reasons 는 PR4 에서 orchestrator 가 채워서 넘긴다.
    """

    def generate_plan(
        self,
        metrics: AdvancedMetrics,
        race_config: RaceConfig,
        include_strength: bool = False,
        training_background: Optional[dict[str, Any]] = None,
        replan_reasons: Optional[list[str]] = None,
    ) -> Optional[TrainingPlan]: ...
