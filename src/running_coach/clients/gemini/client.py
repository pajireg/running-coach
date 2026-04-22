"""Gemini AI 클라이언트 (legacy ↔ llm_driven 디스패처)."""

from datetime import date
from typing import TYPE_CHECKING, Any, Literal, Optional

from google import genai
from google.genai import types

from ...clients.llm import AnthropicMessagesJSONClient, JSONLLMClient, OpenAIResponsesJSONClient
from ...config.constants import GEMINI_MODEL
from ...exceptions import GeminiError
from ...models.config import RaceConfig
from ...models.metrics import AdvancedMetrics
from ...models.training import DailyPlan, TrainingPlan
from ...utils.logger import get_logger
from .planner import TrainingPlanner
from .response_parser import parse_gemini_json

if TYPE_CHECKING:
    from ...coaching.context import CoachingContextBuilder
    from ...coaching.planners.base import Planner
    from ...coaching.safety.validator import SafetyValidator

logger = get_logger(__name__)


PlannerMode = Literal["legacy", "llm_driven"]


class GeminiJSONClient:
    """Google Gemini JSON adapter."""

    provider = "gemini"

    def __init__(self, client: Any, model: str):
        self._client = client
        self.model = model

    def invoke_json(self, prompt: str) -> dict[str, Any]:
        response = self._client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        raw_text = response.text or ""
        if not raw_text:
            raise GeminiError("Empty response from Gemini")
        return parse_gemini_json(raw_text)


class GeminiClient:
    """Gemini AI 클라이언트.

    mode 에 따라 LegacySkeletonPlanner 또는 LLMDrivenPlanner 로 dispatch.
    """

    def __init__(
        self,
        api_key: str,
        mode: PlannerMode = "legacy",
        model: str = GEMINI_MODEL,
        llm_provider: str = "gemini",
        openai_api_key: Optional[str] = None,
        anthropic_api_key: Optional[str] = None,
        context_builder: Optional["CoachingContextBuilder"] = None,
        safety_validator: Optional["SafetyValidator"] = None,
    ):
        if not api_key:
            raise GeminiError("Missing Gemini API key")

        self.api_key = api_key
        self.model = model
        self.llm_provider = llm_provider
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
            llm_client: Optional[JSONLLMClient] = None
            if llm_provider == "openai":
                llm_client = OpenAIResponsesJSONClient(
                    api_key=openai_api_key or "",
                    model=model,
                )
            elif llm_provider == "anthropic":
                llm_client = AnthropicMessagesJSONClient(
                    api_key=anthropic_api_key or "",
                    model=model,
                )
            self._llm = LLMDrivenPlanner(
                gemini_client=self.client,
                model=model,
                context_builder=context_builder,
                safety_validator=safety_validator,
                legacy_fallback=self._legacy,
                llm_client=llm_client,
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

        logger.info("훈련 계획 생성 (planner=%s, llm_provider=%s)", self._mode, self.llm_provider)
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
