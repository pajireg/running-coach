"""LLMDrivenPlanner: context → prompt → Gemini → Pydantic → SafetyValidator 파이프라인.

알고리즘이 결정하는 것: 점수·pace safety bounds·안전 제약.
LLM 이 결정하는 것: 세션 타입 배치·주간 볼륨·duration·step 구성·페이스·phase 해석.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any, Optional, cast

from ...clients.gemini.response_parser import parse_gemini_json
from ...exceptions import GeminiQuotaExceededError, GeminiResponseParseError
from ...models.config import RaceConfig
from ...models.metrics import AdvancedMetrics
from ...models.training import DailyPlan, TrainingPlan
from ...utils.logger import get_logger
from ..prompt import LLMPromptTemplate
from ..safety.metrics import emit_plan_generated
from ..safety.validator import SafetyValidator

if TYPE_CHECKING:
    from ..context import CoachingContextBuilder
    from .legacy import LegacySkeletonPlanner


logger = get_logger(__name__)


class LLMDrivenPlanner:
    """Gemini 기반 Planner. Quota / 파싱 실패 시 legacy fallback."""

    def __init__(
        self,
        gemini_client: Any,
        context_builder: "CoachingContextBuilder",
        safety_validator: SafetyValidator,
        legacy_fallback: "LegacySkeletonPlanner",
    ):
        self._client = gemini_client
        self._context_builder = context_builder
        self._safety = safety_validator
        self._fallback = legacy_fallback

    def generate_plan(
        self,
        metrics: AdvancedMetrics,
        race_config: RaceConfig,
        include_strength: bool = False,
        training_background: Optional[dict[str, Any]] = None,  # noqa: ARG002 — PR2 builder 사용
        replan_reasons: Optional[list[str]] = None,
    ) -> Optional[TrainingPlan]:
        try:
            ctx = self._context_builder.build(
                metrics=metrics,
                race_config=race_config,
                replan_reasons=replan_reasons,
            )
        except Exception as exc:
            logger.exception("CoachingContext 조립 실패; legacy fallback (%s)", exc)
            return self._legacy_fallback(
                metrics, race_config, training_background, include_strength
            )

        safety_descriptions = self._safety.describe_rules(ctx)
        prompt = LLMPromptTemplate.render(
            ctx,
            safety_rules=safety_descriptions,
            include_strength=include_strength,
        )

        try:
            raw_json = self._invoke_gemini(prompt)
        except GeminiQuotaExceededError:
            logger.warning("Gemini quota 초과; legacy fallback")
            return self._legacy_fallback(
                metrics, race_config, training_background, include_strength
            )
        except Exception as exc:
            logger.exception("Gemini 호출 실패; legacy fallback (%s)", exc)
            return self._legacy_fallback(
                metrics, race_config, training_background, include_strength
            )

        try:
            plan = TrainingPlan.model_validate(raw_json)
        except Exception as exc:
            logger.exception("LLM 출력 Pydantic 검증 실패; legacy fallback (%s)", exc)
            return self._legacy_fallback(
                metrics, race_config, training_background, include_strength
            )

        result = self._safety.validate(plan, ctx)
        emit_plan_generated(
            mode="llm_driven",
            violation_count=len(result.violations),
            unresolvable=result.unresolvable,
        )
        if result.unresolvable:
            logger.warning(
                "SafetyValidator 수렴 실패 (%d violations); legacy fallback",
                len(result.violations),
            )
            return self._legacy_fallback(
                metrics, race_config, training_background, include_strength
            )

        logger.info(
            "LLMDrivenPlanner 완료: %d 위반 auto-correct",
            len(result.violations),
        )
        return result.plan

    def extend_plan(
        self,
        existing_days: list[DailyPlan],
        new_date: date,
        metrics: AdvancedMetrics,
        race_config: RaceConfig,
        include_strength: bool = False,
    ) -> Optional[TrainingPlan]:
        """기존 6일 유지 + 신규 1일 LLM 생성 → 7일 TrainingPlan 반환."""
        if len(existing_days) != 6:
            logger.warning(
                "extend_plan: existing_days=%d (6 필요); full replan fallback",
                len(existing_days),
            )
            return self.generate_plan(
                metrics,
                race_config,
                include_strength=include_strength,
                replan_reasons=["extend_fallback_insufficient_days"],
            )

        try:
            ctx = self._context_builder.build(
                metrics=metrics,
                race_config=race_config,
                replan_reasons=["normal_execution_extend"],
            )
        except Exception as exc:
            logger.exception("CoachingContext 조립 실패; full replan fallback (%s)", exc)
            return self.generate_plan(
                metrics,
                race_config,
                include_strength=include_strength,
                replan_reasons=["extend_fallback_context_error"],
            )

        safety_descriptions = self._safety.describe_rules(ctx)
        prompt = LLMPromptTemplate.render_extend(
            ctx,
            existing_days=existing_days,
            new_date=new_date,
            safety_rules=safety_descriptions,
            include_strength=include_strength,
        )

        try:
            raw_json = self._invoke_gemini(prompt)
        except GeminiQuotaExceededError:
            logger.warning("Gemini quota 초과; full replan fallback")
            return self.generate_plan(
                metrics,
                race_config,
                include_strength=include_strength,
                replan_reasons=["extend_fallback_quota"],
            )
        except Exception as exc:
            logger.exception("Gemini 호출 실패; full replan fallback (%s)", exc)
            return self.generate_plan(
                metrics,
                race_config,
                include_strength=include_strength,
                replan_reasons=["extend_fallback_gemini_error"],
            )

        try:
            new_day = DailyPlan.model_validate(raw_json)
        except Exception as exc:
            logger.exception("extend_plan 파싱 실패; full replan fallback (%s)", exc)
            return self.generate_plan(
                metrics,
                race_config,
                include_strength=include_strength,
                replan_reasons=["extend_fallback_parse_error"],
            )

        try:
            plan = TrainingPlan(plan=list(existing_days) + [new_day])
        except Exception as exc:
            logger.exception("TrainingPlan 조립 실패; full replan fallback (%s)", exc)
            return self.generate_plan(
                metrics,
                race_config,
                include_strength=include_strength,
                replan_reasons=["extend_fallback_assemble_error"],
            )

        result = self._safety.validate(plan, ctx)
        emit_plan_generated(
            mode="llm_driven_extend",
            violation_count=len(result.violations),
            unresolvable=result.unresolvable,
        )
        if result.unresolvable:
            logger.warning(
                "SafetyValidator 수렴 실패 (%d violations); full replan fallback",
                len(result.violations),
            )
            return self.generate_plan(
                metrics,
                race_config,
                include_strength=include_strength,
                replan_reasons=["extend_fallback_safety"],
            )

        logger.info(
            "LLMDrivenPlanner.extend_plan 완료: 기존 %d일 유지 + 1일 추가, %d 위반 auto-correct",
            len(existing_days),
            len(result.violations),
        )
        return result.plan

    # ------------------------------------------------------------------

    def _invoke_gemini(self, prompt: str) -> dict[str, Any]:
        """Gemini structured JSON 호출. 재시도·파싱은 내부 메서드가 담당."""
        from google.genai import types  # lazy import

        from ...config.constants import GEMINI_MODEL

        response = self._client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        raw_text = response.text or ""
        if not raw_text:
            raise GeminiResponseParseError("Empty response from Gemini")
        return parse_gemini_json(raw_text)

    def _legacy_fallback(
        self,
        metrics: AdvancedMetrics,
        race_config: RaceConfig,
        training_background: Optional[dict[str, Any]],
        include_strength: bool = False,
    ) -> Optional[TrainingPlan]:
        return cast(
            Optional[TrainingPlan],
            self._fallback.generate_plan(
                metrics,
                race_config,
                include_strength=include_strength,
                training_background=training_background,
            ),
        )
