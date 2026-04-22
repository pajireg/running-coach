"""Gemini AI 클라이언트 (legacy ↔ llm_driven 디스패처)."""

from datetime import date
from typing import TYPE_CHECKING, Any, Literal, Optional

from google import genai

from ...exceptions import GeminiError
from ...models.config import RaceConfig
from ...models.metrics import AdvancedMetrics
from ...models.training import DailyPlan, TrainingPlan
from ...utils.logger import get_logger
from .planner import TrainingPlanner

if TYPE_CHECKING:
    from ...coaching.context import CoachingContextBuilder
    from ...coaching.planners.base import Planner
    from ...coaching.safety.validator import SafetyValidator

logger = get_logger(__name__)


PlannerMode = Literal["legacy", "llm_driven"]


class GeminiClient:
    """Gemini AI 클라이언트.

    mode 에 따라 LegacySkeletonPlanner 또는 LLMDrivenPlanner 로 dispatch.
    """

    def __init__(
        self,
        api_key: str,
        mode: PlannerMode = "legacy",
        context_builder: Optional["CoachingContextBuilder"] = None,
        safety_validator: Optional["SafetyValidator"] = None,
    ):
        if not api_key:
            raise GeminiError("Missing Gemini API key")

        self.api_key = api_key
        self.client = genai.Client(api_key=api_key)
        self.planner: TrainingPlanner = TrainingPlanner(self.client)
        self._mode: PlannerMode = mode

        if context_builder is None or safety_validator is None:
            raise GeminiError(
                "context_builder and safety_validator are required for both legacy and llm_driven"
            )

        # lazy import → 순환 의존 방지
        from ...coaching.planners.legacy import LegacySkeletonPlanner

        self._legacy: "Planner" = LegacySkeletonPlanner(
            inner=self.planner,
            context_builder=context_builder,
            safety_validator=safety_validator,
        )
        self._llm: Optional["Planner"] = None

        if mode == "llm_driven":
            from ...coaching.planners.llm_driven import LLMDrivenPlanner

            assert isinstance(self._legacy, LegacySkeletonPlanner)
            self._llm = LLMDrivenPlanner(
                gemini_client=self.client,
                context_builder=context_builder,
                safety_validator=safety_validator,
                legacy_fallback=self._legacy,
            )

    @property
    def mode(self) -> PlannerMode:
        return self._mode

    def create_training_plan(
        self,
        metrics: AdvancedMetrics,
        race_config: RaceConfig,
        include_strength: bool = False,
        training_background: Optional[dict[str, Any]] = None,
        replan_reasons: Optional[list[str]] = None,
    ) -> Optional[TrainingPlan]:
        """훈련 계획 생성. mode 에 따라 sub-planner 호출."""
        active: "Planner"
        if self._mode == "llm_driven" and self._llm is not None:
            active = self._llm
        else:
            active = self._legacy

        logger.info("훈련 계획 생성 (planner=%s)", self._mode)
        return active.generate_plan(
            metrics,
            race_config,
            include_strength=include_strength,
            training_background=training_background,
            replan_reasons=replan_reasons,
        )

    def extend_training_plan(
        self,
        existing_days: list[DailyPlan],
        new_date: date,
        metrics: AdvancedMetrics,
        race_config: RaceConfig,
        include_strength: bool = False,
    ) -> Optional[TrainingPlan]:
        """llm_driven 모드에서 기존 6일 유지 + 1일 연장. legacy 모드는 전체 재생성."""
        if self._mode == "llm_driven" and self._llm is not None:
            from ...coaching.planners.llm_driven import LLMDrivenPlanner

            if isinstance(self._llm, LLMDrivenPlanner):
                logger.info("훈련 계획 연장 (planner=llm_driven_extend)")
                return self._llm.extend_plan(
                    existing_days=existing_days,
                    new_date=new_date,
                    metrics=metrics,
                    race_config=race_config,
                    include_strength=include_strength,
                )

        logger.info("훈련 계획 연장 (planner=%s, fallback to full replan)", self._mode)
        return self.create_training_plan(
            metrics=metrics,
            race_config=race_config,
            include_strength=include_strength,
            replan_reasons=["extend_fallback_legacy"],
        )
