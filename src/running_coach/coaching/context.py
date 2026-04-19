"""CoachingContext: LLM·SafetyValidator 에 전달되는 입력 모음.

PR1 범위에서는 SafetyValidator 가 필요한 최소 필드만 정의한다.
PR2 에서 CoachingContextBuilder 가 history_service 결과를 이 형태로 변환한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Mapping, Optional

from ..core.pace_zones import PaceZones


@dataclass(frozen=True)
class AvailabilitySlot:
    """요일별 훈련 가용성."""

    weekday: int  # 0=Monday ... 6=Sunday
    is_available: bool = True
    max_duration_minutes: Optional[int] = None
    preferred_session_type: Optional[str] = None


@dataclass(frozen=True)
class CoachingScores:
    """알고리즘이 결정적으로 산출한 선수 상태 점수."""

    readiness: float
    fatigue: float
    injury_risk: float
    active_injury_severity: int = 0
    chronic_ewma_load: float = 0.0  # ACWR 계산용; 0 이면 비활성
    staleness_days: int = 0


@dataclass(frozen=True)
class CoachingContext:
    """SafetyValidator 및 LLM 프롬프트의 공유 입력.

    PR2 에서 CoachingContextBuilder 가 다음 필드를 추가한다:
        metrics, execution_history_14d, active_injuries,
        subjective_feedback, race, training_block,
        training_background, replan_reasons, safety_rules_summary.
    """

    today: date
    scores: CoachingScores
    pace_zones: PaceZones
    availability: Mapping[int, AvailabilitySlot] = field(default_factory=dict)

    def availability_for(self, weekday: int) -> AvailabilitySlot:
        """해당 요일 가용성 반환 (없으면 기본값)."""
        return self.availability.get(weekday, AvailabilitySlot(weekday=weekday))
