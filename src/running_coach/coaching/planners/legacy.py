"""LegacySkeletonPlanner: LLM 없는 순수 알고리즘 플래너.

skeleton 배치(_build_weekly_skeleton) → StepTemplateEngine → DescriptionRenderer
→ SafetyValidator 파이프라인. Gemini API 를 전혀 호출하지 않는다.

Free tier 용. llm_driven 과 동일한 SafetyValidator(15 rules)를 공유한다.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any, Optional

from ...coaching.safety.metrics import emit_plan_generated
from ...models.config import RaceConfig
from ...models.metrics import AdvancedMetrics
from ...models.training import DailyPlan, TrainingPlan
from ...utils.logger import get_logger
from .description_renderer import DescriptionRenderer
from .step_templates import QualitySubtypeSelector, StepTemplateEngine

if TYPE_CHECKING:
    from ...clients.gemini.planner import TrainingPlanner
    from ...coaching.context import CoachingContextBuilder
    from ...coaching.safety.validator import SafetyValidator

logger = get_logger(__name__)


class LegacySkeletonPlanner:
    """순수 알고리즘 기반 플래너 (LLM 호출 없음). Free tier 용.

    재사용하는 것:
    - TrainingPlanner._build_weekly_skeleton — session 배치·볼륨 결정
    - SafetyValidator — llm_driven 과 동일한 15개 안전 룰

    새로 추가된 것:
    - StepTemplateEngine — session_type 별 결정론적 step 구조
    - QualitySubtypeSelector — phase·컨디션 기반 quality 세부 종류 결정
    - DescriptionRenderer — 템플릿 기반 한국어 설명
    """

    def __init__(
        self,
        inner: "TrainingPlanner",
        context_builder: "CoachingContextBuilder",
        safety_validator: "SafetyValidator",
    ):
        self._inner = inner
        self._context_builder = context_builder
        self._safety = safety_validator

    def generate_plan(
        self,
        metrics: AdvancedMetrics,
        race_config: RaceConfig,
        include_strength: bool = False,  # noqa: ARG002
        training_background: Optional[dict[str, Any]] = None,
        replan_reasons: Optional[list[str]] = None,  # noqa: ARG002
    ) -> Optional[TrainingPlan]:
        # 1. 7일 skeleton: 요일 배치 + target_minutes + pace (기존 알고리즘 재사용)
        skeleton = self._inner._build_weekly_skeleton(metrics, race_config, training_background)

        # 2. coaching context: pace_zones + scores + injury + training_block
        try:
            ctx = self._context_builder.build(
                metrics=metrics,
                race_config=race_config,
                replan_reasons=[],
            )
        except Exception as exc:
            logger.exception("CoachingContext 조립 실패; skeleton fallback (%s)", exc)
            return self._skeleton_fallback(metrics, skeleton)

        phase: str = (ctx.training_block.phase or "base") if ctx.training_block else "base"
        quality_subtype = QualitySubtypeSelector.pick(
            phase=phase,
            readiness=ctx.scores.readiness,
            injury_risk=ctx.scores.injury_risk,
        )

        # 3. skeleton → DailyPlan 조립 (step 템플릿 + description 템플릿)
        daily_plans: list[DailyPlan] = []
        for sk_day in skeleton:
            session_type = sk_day["sessionType"]
            target_minutes = int(sk_day.get("targetMinutes") or 0)
            workout_name = str(sk_day.get("workoutName") or "Base Run")

            steps = StepTemplateEngine.build(
                session_type=session_type,
                target_minutes=target_minutes,
                pace_zones=ctx.pace_zones,
                quality_subtype=quality_subtype,
            )
            description = DescriptionRenderer.render(
                session_type=session_type,
                quality_subtype=quality_subtype if session_type == "quality" else None,
                ctx=ctx,
            )
            try:
                daily_plans.append(
                    DailyPlan.model_validate(
                        {
                            "date": date.fromisoformat(sk_day["date"]),
                            "sessionType": session_type,
                            "plannedMinutes": target_minutes,
                            "workout": {
                                "workoutName": workout_name,
                                "description": description,
                                "sportType": "RUNNING",
                                "steps": [s.model_dump(by_alias=True) for s in steps],
                            },
                        }
                    )
                )
            except Exception as exc:
                logger.warning("DailyPlan 조립 실패 %s: %s", sk_day.get("date"), exc)
                return self._skeleton_fallback(metrics, skeleton)

        try:
            plan = TrainingPlan(plan=daily_plans)
        except Exception as exc:
            logger.exception("TrainingPlan 조립 실패: %s", exc)
            return self._skeleton_fallback(metrics, skeleton)

        # 4. SafetyValidator — llm_driven 과 동일한 15개 룰 적용
        result = self._safety.validate(plan, ctx)
        emit_plan_generated(
            mode="legacy_algorithmic",
            violation_count=len(result.violations),
            unresolvable=result.unresolvable,
        )
        if result.unresolvable:
            logger.warning(
                "SafetyValidator 수렴 실패 (%d violations); raw plan 반환",
                len(result.violations),
            )
            return plan

        logger.info(
            "LegacySkeletonPlanner 완료: %d 위반 auto-correct",
            len(result.violations),
        )
        return result.plan

    def _skeleton_fallback(
        self, metrics: AdvancedMetrics, skeleton: list[dict[str, Any]]
    ) -> Optional[TrainingPlan]:
        """skeleton 만으로 최소 plan 반환 (step 없이). 최후 수단."""
        fallback_json = self._inner._fallback_plan_json(metrics, skeleton)
        try:
            return TrainingPlan(**fallback_json)
        except Exception:
            return None
