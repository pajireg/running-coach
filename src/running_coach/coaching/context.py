"""CoachingContext: LLM·SafetyValidator 에 전달되는 입력 모음.

LLM 이 코칭 판단을 직접 내리기 위해 필요한 모든 raw context 를 담는다.
점수화(readiness/fatigue/injury)와 pace zones 는 여전히 알고리즘이 결정하지만
`planning_notes` 같은 해석이 담긴 문자열은 포함하지 않는다 (LLM 에 threshold leak 방지).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping, Optional

from ..core.pace_zones import PaceZoneEngine, PaceZones
from ..models.config import RaceConfig
from ..models.metrics import AdvancedMetrics


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
    staleness_days: Optional[int] = None


@dataclass(frozen=True)
class ExecutionDay:
    """최근 실제 수행 세션의 raw 기록 (해석 없음)."""

    date: date
    planned_category: Optional[str] = None
    actual_category: Optional[str] = None
    distance_km: Optional[float] = None
    duration_seconds: Optional[int] = None
    avg_pace: Optional[str] = None
    avg_hr: Optional[int] = None
    execution_status: Optional[str] = None
    deviation_reason: Optional[str] = None
    coach_interpretation: Optional[str] = None
    match_score: Optional[float] = None


@dataclass(frozen=True)
class InjurySnapshot:
    """활성 부상 상태 (severity 0 이면 부상 없음)."""

    injury_area: Optional[str] = None
    severity: int = 0
    status_date: Optional[date] = None
    notes: Optional[str] = None

    @property
    def is_active(self) -> bool:
        return self.severity > 0


@dataclass(frozen=True)
class FeedbackSnapshot:
    """주관적 피드백 1건 + staleness."""

    feedback_date: Optional[date] = None
    fatigue_score: Optional[int] = None
    soreness_score: Optional[int] = None
    stress_score: Optional[int] = None
    motivation_score: Optional[int] = None
    sleep_quality_score: Optional[int] = None
    pain_notes: Optional[str] = None
    notes: Optional[str] = None
    staleness_days: Optional[int] = None


@dataclass(frozen=True)
class TrainingBlockSnapshot:
    """사용자가 설정한 훈련 블록 (없으면 phase None)."""

    phase: Optional[str] = None
    focus: Optional[str] = None
    weekly_volume_target_km: Optional[float] = None
    starts_on: Optional[date] = None
    ends_on: Optional[date] = None


@dataclass(frozen=True)
class RaceGoalSnapshot:
    """사용자가 설정한 목표 레이스."""

    goal_name: Optional[str] = None
    race_date: Optional[date] = None
    distance: Optional[str] = None
    goal_time: Optional[str] = None
    target_pace: Optional[str] = None


@dataclass(frozen=True)
class TrainingBackground:
    """최근 6주·12개월·평생 러닝 배경 (raw 집계)."""

    recent_6_weeks: list[dict[str, Any]] = field(default_factory=list)
    recent_12_months: list[dict[str, Any]] = field(default_factory=list)
    lifetime: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CoachingContext:
    """LLM 프롬프트 + SafetyValidator 가 공유하는 입력.

    순서는 deterministic: 같은 입력 → 같은 직렬화 (Gemini prompt cache 친화).
    """

    today: date
    scores: CoachingScores
    pace_zones: PaceZones
    metrics: Optional[AdvancedMetrics] = None
    availability: Mapping[int, AvailabilitySlot] = field(default_factory=dict)
    execution_history_14d: list[ExecutionDay] = field(default_factory=list)
    active_injury: InjurySnapshot = field(default_factory=InjurySnapshot)
    recent_feedback: list[FeedbackSnapshot] = field(default_factory=list)
    training_block: Optional[TrainingBlockSnapshot] = None
    race_goal: Optional[RaceGoalSnapshot] = None
    training_background: TrainingBackground = field(default_factory=TrainingBackground)
    replan_reasons: list[str] = field(default_factory=list)

    def availability_for(self, weekday: int) -> AvailabilitySlot:
        """해당 요일 가용성 반환 (없으면 기본값)."""
        return self.availability.get(weekday, AvailabilitySlot(weekday=weekday))


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def _parse_iso_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


class CoachingContextBuilder:
    """history_service 결과 + race_config + replan reasons → CoachingContext.

    history_service 는 runtime 에 주입되어 PR2 이후 테스트가 mock 하기 쉽다.
    """

    def __init__(self, history_service: Any, pace_engine: Any = PaceZoneEngine):
        self._history = history_service
        self._pace_engine = pace_engine

    def build(
        self,
        metrics: AdvancedMetrics,
        race_config: RaceConfig,
        replan_reasons: Optional[list[str]] = None,
    ) -> CoachingContext:
        as_of = metrics.date
        background_raw = self._history.summarize_training_background(as_of)
        coaching_state = background_raw.get("coachingState") or {}
        planning_constraints = background_raw.get("planningConstraints") or {}
        pace_zones = self._pace_engine.calculate(metrics, race_config)
        scores = self._build_scores(coaching_state)
        availability = self._build_availability(planning_constraints.get("availability") or [])
        execution_history = self._build_execution_history(as_of)
        active_injury = self._build_active_injury(coaching_state.get("activeInjury") or {})
        recent_feedback = self._build_recent_feedback(
            coaching_state.get("subjectiveFeedback") or {}, as_of
        )
        training_block = self._build_training_block(planning_constraints.get("trainingBlock") or {})
        race_goal = self._build_race_goal(planning_constraints.get("raceGoal") or {})
        training_background = TrainingBackground(
            recent_6_weeks=list(background_raw.get("recent6Weeks") or []),
            recent_12_months=list(background_raw.get("recent12Months") or []),
            lifetime=dict(background_raw.get("lifetime") or {}),
        )
        return CoachingContext(
            today=as_of,
            metrics=metrics,
            scores=scores,
            pace_zones=pace_zones,
            availability=availability,
            execution_history_14d=execution_history,
            active_injury=active_injury,
            recent_feedback=recent_feedback,
            training_block=training_block,
            race_goal=race_goal,
            training_background=training_background,
            replan_reasons=list(replan_reasons or []),
        )

    # -- field builders -----------------------------------------------------

    def _build_scores(self, coaching_state: dict[str, Any]) -> CoachingScores:
        load = coaching_state.get("load") or {}
        active_injury = coaching_state.get("activeInjury") or {}
        return CoachingScores(
            readiness=float(coaching_state.get("readinessScore") or 50.0),
            fatigue=float(coaching_state.get("fatigueScore") or 50.0),
            injury_risk=float(coaching_state.get("injuryRiskScore") or 20.0),
            active_injury_severity=int(active_injury.get("severity") or 0),
            chronic_ewma_load=float(load.get("chronicEwmaLoad") or 0.0),
        )

    def _build_availability(
        self,
        raw_rows: list[dict[str, Any]],
    ) -> Mapping[int, AvailabilitySlot]:
        result: dict[int, AvailabilitySlot] = {}
        for row in raw_rows:
            weekday = int(row.get("weekday") or 0)
            result[weekday] = AvailabilitySlot(
                weekday=weekday,
                is_available=bool(row.get("isAvailable", True)),
                max_duration_minutes=(
                    int(row["maxDurationMinutes"])
                    if row.get("maxDurationMinutes") is not None
                    else None
                ),
                preferred_session_type=row.get("preferredSessionType"),
            )
        return result

    def _build_execution_history(self, as_of: date) -> list[ExecutionDay]:
        if not hasattr(self._history, "list_recent_completed_activities"):
            return []
        rows = self._history.list_recent_completed_activities(as_of, days=14) or []
        out: list[ExecutionDay] = []
        for row in rows:
            # history_service 가 camelCase 키 반환. 호환을 위해 양쪽 다 시도.
            def pick(camel: str, snake: str) -> Any:
                return row.get(camel, row.get(snake))

            activity_date = _parse_iso_date(pick("activityDate", "activity_date")) or as_of
            distance = pick("distanceKm", "distance_km")
            duration = pick("durationSeconds", "duration_seconds")
            avg_hr = pick("avgHr", "avg_hr")
            match_score = pick("targetMatchScore", "target_match_score")
            out.append(
                ExecutionDay(
                    date=activity_date,
                    planned_category=pick("plannedCategory", "planned_category"),
                    actual_category=pick("actualCategory", "actual_category"),
                    distance_km=float(distance) if distance is not None else None,
                    duration_seconds=int(duration) if duration is not None else None,
                    avg_pace=pick("avgPace", "avg_pace"),
                    avg_hr=int(avg_hr) if avg_hr is not None else None,
                    execution_status=pick("executionStatus", "execution_status"),
                    deviation_reason=pick("deviationReason", "deviation_reason"),
                    coach_interpretation=pick("coachInterpretation", "coach_interpretation"),
                    match_score=float(match_score) if match_score is not None else None,
                )
            )
        return out

    def _build_active_injury(self, raw: dict[str, Any]) -> InjurySnapshot:
        severity = int(raw.get("severity") or 0)
        if severity <= 0:
            return InjurySnapshot()
        return InjurySnapshot(
            injury_area=raw.get("injuryArea"),
            severity=severity,
            status_date=_parse_iso_date(raw.get("statusDate")),
            notes=raw.get("notes"),
        )

    def _build_recent_feedback(
        self,
        raw: dict[str, Any],
        as_of: date,
    ) -> list[FeedbackSnapshot]:
        """현재는 history_service 가 1건만 반환. 미래 확장 위해 list 로 감쌈."""
        feedback_date = _parse_iso_date(raw.get("feedbackDate"))
        if feedback_date is None and not any(
            raw.get(key) is not None
            for key in (
                "fatigueScore",
                "sorenessScore",
                "stressScore",
                "motivationScore",
                "sleepQualityScore",
                "painNotes",
                "notes",
            )
        ):
            return []
        staleness_days: Optional[int] = None
        if feedback_date is not None:
            staleness_days = max(0, (as_of - feedback_date).days)
        return [
            FeedbackSnapshot(
                feedback_date=feedback_date,
                fatigue_score=raw.get("fatigueScore"),
                soreness_score=raw.get("sorenessScore"),
                stress_score=raw.get("stressScore"),
                motivation_score=raw.get("motivationScore"),
                sleep_quality_score=raw.get("sleepQualityScore"),
                pain_notes=raw.get("painNotes"),
                notes=raw.get("notes"),
                staleness_days=staleness_days,
            )
        ]

    def _build_training_block(
        self,
        raw: dict[str, Any],
    ) -> Optional[TrainingBlockSnapshot]:
        if not raw or raw.get("phase") is None:
            return None
        weekly = raw.get("weeklyVolumeTargetKm")
        return TrainingBlockSnapshot(
            phase=raw.get("phase"),
            focus=raw.get("focus"),
            weekly_volume_target_km=float(weekly) if weekly is not None else None,
            starts_on=_parse_iso_date(raw.get("startsOn")),
            ends_on=_parse_iso_date(raw.get("endsOn")),
        )

    def _build_race_goal(self, raw: dict[str, Any]) -> Optional[RaceGoalSnapshot]:
        if not raw or not any(raw.get(k) for k in ("goalName", "raceDate", "distance")):
            return None
        return RaceGoalSnapshot(
            goal_name=raw.get("goalName"),
            race_date=_parse_iso_date(raw.get("raceDate")),
            distance=raw.get("distance"),
            goal_time=raw.get("goalTime"),
            target_pace=raw.get("targetPace"),
        )
