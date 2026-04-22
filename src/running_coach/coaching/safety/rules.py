"""안전 룰 카탈로그 + 14개 구체 룰.

각 Rule 은 check(plan, ctx) → list[Violation] 와
correct(plan, ctx, violations) → TrainingPlan 을 제공한다.
Violation 은 day_index 포함 stable identity 를 가지며 validator 의
루프 감지에 사용된다.

DEFAULT_SAFETY_RULES 순서 = 실행·보정 순서.
구조적(session_type 변경) 룰 → 볼륨/가용성 → step-level → pace 정합성.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Optional, Protocol, cast, runtime_checkable

if TYPE_CHECKING:
    from ...core.pace_zones import PaceBand, PaceCapabilityProfile, PaceZones
    from ...models.training import DailyPlan, SessionType, TrainingPlan
    from ..context import CoachingContext


Severity = Literal["warn", "block"]

_PACE_RE = re.compile(r"(\d+):(\d{2})")


# ---------------------------------------------------------------------------
# Violation & Rule protocol
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Violation:
    """룰 위반 1건.

    (rule_id, day_index) 조합은 validator 의 루프 감지 키.
    """

    rule_id: str
    severity: Severity
    message: str
    day_index: Optional[int] = None

    @property
    def identity(self) -> tuple[str, Optional[int]]:
        return (self.rule_id, self.day_index)


@runtime_checkable
class SafetyRule(Protocol):
    rule_id: str
    severity: Severity

    def check(self, plan: "TrainingPlan", ctx: "CoachingContext") -> list[Violation]: ...
    def correct(
        self,
        plan: "TrainingPlan",
        ctx: "CoachingContext",
        violations: list[Violation],
    ) -> "TrainingPlan": ...
    def describe(self, ctx: "CoachingContext") -> str: ...


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_WORKOUT_NAMES: dict[str, str] = {
    "rest": "Rest Day",
    "recovery": "Recovery Run",
    "base": "Base Run",
    "quality": "Interval",
    "long_run": "Long Run",
}


def _pace_seconds(pace: str) -> Optional[int]:
    m = _PACE_RE.fullmatch(pace.strip())
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def _pace_for_step(
    pace_zones: "PaceZones",
    step_type: str,
    session_type: str,
) -> str:
    return pace_zones.for_step(step_type, session_type)


def _format_pace(seconds: int) -> str:
    bounded = max(180, min(seconds, 600))
    return f"{bounded // 60}:{bounded % 60:02d}"


def _pace_profile(ctx: "CoachingContext") -> "PaceCapabilityProfile":
    if ctx.pace_profile is not None:
        return ctx.pace_profile
    from ...core.pace_zones import PaceCapabilityProfile

    return PaceCapabilityProfile.from_zones(ctx.pace_zones)


def _pace_band_for_step(ctx: "CoachingContext", step_type: str, session_type: str) -> "PaceBand":
    return _pace_profile(ctx).band_for_step(step_type, session_type)


def _pace_within_band(pace_seconds: int, band: "PaceBand") -> bool:
    fast = _pace_seconds(band.fast)
    slow = _pace_seconds(band.slow)
    if fast is None or slow is None:
        return False
    return fast <= pace_seconds <= slow


def _clamp_pace_to_band(pace_seconds: int, band: "PaceBand") -> str:
    fast = _pace_seconds(band.fast)
    slow = _pace_seconds(band.slow)
    if fast is None or slow is None:
        return _format_pace(pace_seconds)
    return _format_pace(max(fast, min(pace_seconds, slow)))


def _step_dict(
    step_type: str,
    duration_seconds: int,
    target_value: str,
    target_type: str = "speed",
) -> dict:
    duration_seconds = max(60, int(duration_seconds))
    return {
        "type": step_type,
        "durationValue": duration_seconds,
        "durationUnit": "second",
        "targetType": target_type,
        "targetValue": target_value,
    }


def _build_step(
    step_type: str,
    duration_seconds: int,
    target_value: str,
    target_type: str = "speed",
):
    from ...models.training import WorkoutStep

    return WorkoutStep.model_validate(
        _step_dict(step_type, duration_seconds, target_value, target_type)
    )


def _default_steps_for(
    session_type: str,
    target_seconds: int,
    pace_zones: "PaceZones",
) -> list[dict]:
    """session_type 별 기본 step 구성 (legacy _default_steps_for_skeleton_day 포팅).

    target_seconds 는 총 duration 의 대략 목표. 세션에 따라 step 들이 합산.
    """
    if session_type == "rest":
        return []
    if session_type == "recovery":
        return [
            _step_dict("Warmup", 300, _pace_for_step(pace_zones, "Warmup", session_type)),
            _step_dict(
                "Run",
                max(target_seconds - 600, 900),
                _pace_for_step(pace_zones, "Run", session_type),
            ),
            _step_dict("Cooldown", 300, _pace_for_step(pace_zones, "Cooldown", session_type)),
        ]
    if session_type == "quality":
        quality_block = max(target_seconds - 1500, 1200)
        repeat = max(3, min(6, quality_block // 360))
        interval_seconds = max(180, quality_block // (repeat * 2))
        steps = [_step_dict("Warmup", 900, _pace_for_step(pace_zones, "Warmup", session_type))]
        for _ in range(repeat):
            steps.append(
                _step_dict(
                    "Interval",
                    interval_seconds,
                    _pace_for_step(pace_zones, "Interval", session_type),
                )
            )
            steps.append(
                _step_dict(
                    "Recovery",
                    interval_seconds,
                    _pace_for_step(pace_zones, "Recovery", session_type),
                )
            )
        steps.append(
            _step_dict("Cooldown", 600, _pace_for_step(pace_zones, "Cooldown", session_type))
        )
        return steps
    if session_type == "long_run":
        return [
            _step_dict("Warmup", 600, _pace_for_step(pace_zones, "Warmup", session_type)),
            _step_dict(
                "Run",
                max(target_seconds - 900, 2700),
                _pace_for_step(pace_zones, "Run", session_type),
            ),
            _step_dict("Cooldown", 300, _pace_for_step(pace_zones, "Cooldown", session_type)),
        ]
    # base
    return [
        _step_dict("Warmup", 600, _pace_for_step(pace_zones, "Warmup", session_type)),
        _step_dict(
            "Run",
            max(target_seconds - 900, 1800),
            _pace_for_step(pace_zones, "Run", session_type),
        ),
        _step_dict("Cooldown", 300, _pace_for_step(pace_zones, "Cooldown", session_type)),
    ]


def _rebuild_day(
    day: "DailyPlan",
    new_session_type: "SessionType",
    pace_zones: "PaceZones",
    planned_minutes: Optional[int] = None,
) -> "DailyPlan":
    """세션 타입 변경 + steps/workout_name/planned_minutes 재구성."""
    from ...models.training import DailyPlan

    if new_session_type == "rest":
        return DailyPlan.model_validate(
            {
                "date": day.date,
                "sessionType": "rest",
                "plannedMinutes": 0,
                "workout": {
                    "workoutName": _WORKOUT_NAMES["rest"],
                    "description": day.workout.description,
                    "sportType": "RUNNING",
                    "steps": [],
                },
            }
        )

    if planned_minutes is None:
        planned_minutes = day.planned_minutes or day.workout.total_duration_minutes
    planned_minutes = max(20, int(planned_minutes))
    steps_raw = _default_steps_for(new_session_type, planned_minutes * 60, pace_zones)
    return DailyPlan.model_validate(
        {
            "date": day.date,
            "sessionType": new_session_type,
            "plannedMinutes": planned_minutes,
            "workout": {
                "workoutName": _WORKOUT_NAMES[new_session_type],
                "description": day.workout.description,
                "sportType": "RUNNING",
                "steps": steps_raw,
            },
        }
    )


def _replace_day(plan: "TrainingPlan", index: int, new_day: "DailyPlan") -> "TrainingPlan":
    """plan 의 index 번째 day 교체."""
    new_days = list(plan.plan)
    new_days[index] = new_day
    return plan.model_copy(update={"plan": new_days})


def _is_hard(day: "DailyPlan") -> bool:
    return day.session_type in ("quality", "long_run")


def _total_planned_km(plan: "TrainingPlan", pace_zones: "PaceZones") -> float:
    """step duration × base pace 로 7일 러닝 km 추정."""
    base_pace_sec = _pace_seconds(pace_zones.to_dict().get("base", "6:45")) or 405
    total_seconds = 0
    for day in plan.plan:
        if day.session_type == "rest":
            continue
        total_seconds += day.workout.total_duration
    if base_pace_sec <= 0:
        return 0.0
    return total_seconds / base_pace_sec


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


class InjuryBlockQuality:
    """활성 부상 severity ≥ 6 → quality 제거, 주간 볼륨 × 0.65."""

    rule_id = "injury_block_quality"
    severity: Severity = "block"

    def check(self, plan, ctx):
        if ctx.scores.active_injury_severity < 6:
            return []
        out: list[Violation] = []
        for i, day in enumerate(plan.plan):
            if day.session_type == "quality":
                out.append(
                    Violation(
                        rule_id=self.rule_id,
                        severity=self.severity,
                        message=(
                            f"active injury severity {ctx.scores.active_injury_severity}"
                            f" → quality on day {i} removed"
                        ),
                        day_index=i,
                    )
                )
        return out

    def correct(self, plan, ctx, violations):
        for v in violations:
            if v.day_index is None:
                continue
            day = plan.plan[v.day_index]
            # quality → recovery, duration × 0.65
            new_minutes = max(20, int((day.planned_minutes or 40) * 0.65))
            new_day = _rebuild_day(day, "recovery", ctx.pace_zones, planned_minutes=new_minutes)
            plan = _replace_day(plan, v.day_index, new_day)
        return plan

    def describe(self, ctx):
        if ctx.scores.active_injury_severity >= 6:
            return "활성 부상 severity 가 높아 이번 주는 quality 세션을 배치하지 않습니다."
        return "활성 부상 severity ≥ 6 일 때 quality 세션을 배치하지 않습니다."


class InjuryReduceVolume:
    """활성 부상 severity 3-5 → Interval step 을 Run(base)로 전환."""

    rule_id = "injury_reduce_volume"
    severity: Severity = "block"

    def check(self, plan, ctx):
        sev = ctx.scores.active_injury_severity
        if not (3 <= sev < 6):
            return []
        out: list[Violation] = []
        for i, day in enumerate(plan.plan):
            has_interval = any(s.type == "Interval" for s in day.workout.steps)
            if has_interval:
                out.append(
                    Violation(
                        rule_id=self.rule_id,
                        severity=self.severity,
                        message=f"injury severity {sev} → intervals removed from day {i}",
                        day_index=i,
                    )
                )
        return out

    def correct(self, plan, ctx, violations):

        base_pace = ctx.pace_zones.to_dict().get("base", "6:45")
        for v in violations:
            if v.day_index is None:
                continue
            day = plan.plan[v.day_index]
            new_steps = []
            for s in day.workout.steps:
                if s.type == "Interval":
                    new_steps.append(_build_step("Run", s.duration_value, base_pace))
                else:
                    new_steps.append(s)
            new_workout = day.workout.model_copy(update={"steps": new_steps})
            new_day = day.model_copy(update={"workout": new_workout})
            plan = _replace_day(plan, v.day_index, new_day)
        return plan

    def describe(self, ctx):
        sev = ctx.scores.active_injury_severity
        if 3 <= sev < 6:
            return "활성 부상이 있어 인터벌 대신 base 강도 러닝으로 대체합니다."
        return "활성 부상 severity 3-5 시 인터벌 대신 base 러닝으로 교체합니다."


class MaxOneLongRun:
    """주간 long_run ≤ 1."""

    rule_id = "max_one_long_run"
    severity: Severity = "block"

    def check(self, plan, ctx):
        long_indexes = [i for i, d in enumerate(plan.plan) if d.session_type == "long_run"]
        if len(long_indexes) <= 1:
            return []
        # 첫 번째는 유지, 나머지 violation
        out: list[Violation] = []
        for i in long_indexes[1:]:
            out.append(
                Violation(
                    rule_id=self.rule_id,
                    severity=self.severity,
                    message=f"extra long_run on day {i} demoted to base",
                    day_index=i,
                )
            )
        return out

    def correct(self, plan, ctx, violations):
        for v in violations:
            if v.day_index is None:
                continue
            day = plan.plan[v.day_index]
            new_day = _rebuild_day(day, "base", ctx.pace_zones)
            plan = _replace_day(plan, v.day_index, new_day)
        return plan

    def describe(self, ctx):
        return "주간 장거리는 정확히 1회입니다."


class PreferLongRunAvailability:
    """long_run 은 사용자가 long_run 선호로 지정한 가용 요일에 배치."""

    rule_id = "prefer_long_run_availability"
    severity: Severity = "block"

    @staticmethod
    def _preferred_weekdays(ctx: "CoachingContext") -> set[int]:
        return {
            weekday
            for weekday, slot in ctx.availability.items()
            if slot.is_available and slot.preferred_session_type == "long_run"
        }

    def _candidate_indexes(self, plan: "TrainingPlan", ctx: "CoachingContext") -> list[int]:
        preferred_weekdays = self._preferred_weekdays(ctx)
        if not preferred_weekdays:
            return []
        return [
            i
            for i, day in enumerate(plan.plan)
            if day.date.weekday() in preferred_weekdays
            and ctx.availability_for(day.date.weekday()).is_available
        ]

    def check(self, plan, ctx):
        preferred_indexes = self._candidate_indexes(plan, ctx)
        if not preferred_indexes:
            return []
        out: list[Violation] = []
        preferred_index_set = set(preferred_indexes)
        for i, day in enumerate(plan.plan):
            if day.session_type == "long_run" and i not in preferred_index_set:
                out.append(
                    Violation(
                        rule_id=self.rule_id,
                        severity=self.severity,
                        message=(
                            f"long_run on day {i} ignores preferred long-run weekdays; "
                            "moving to preferred availability"
                        ),
                        day_index=i,
                    )
                )
        return out

    def correct(self, plan, ctx, violations):
        preferred_indexes = self._candidate_indexes(plan, ctx)
        if not preferred_indexes:
            return plan
        long_index = next((v.day_index for v in violations if v.day_index is not None), None)
        if long_index is None:
            return plan

        old_long_day = plan.plan[long_index]
        old_long_minutes = (
            old_long_day.planned_minutes or old_long_day.workout.total_duration_minutes
        )
        target_index = self._choose_target_index(plan, ctx, preferred_indexes, old_long_minutes)
        if target_index == long_index:
            return plan

        target_day = plan.plan[target_index]
        replacement_type = cast("SessionType", target_day.session_type or "base")
        replacement_minutes = (
            target_day.planned_minutes or target_day.workout.total_duration_minutes
        )

        new_target = _rebuild_day(
            target_day,
            "long_run",
            ctx.pace_zones,
            planned_minutes=old_long_minutes,
        )
        new_old = _rebuild_day(
            old_long_day,
            replacement_type,
            ctx.pace_zones,
            planned_minutes=replacement_minutes,
        )
        plan = _replace_day(plan, target_index, new_target)
        return _replace_day(plan, long_index, new_old)

    @staticmethod
    def _choose_target_index(
        plan: "TrainingPlan",
        ctx: "CoachingContext",
        preferred_indexes: list[int],
        long_run_minutes: int,
    ) -> int:
        def score(index: int) -> tuple[int, int, int]:
            day = plan.plan[index]
            weekday = day.date.weekday()
            max_minutes = ctx.availability_for(weekday).max_duration_minutes
            enough_time = int(max_minutes is None or max_minutes >= long_run_minutes)
            weekend = int(weekday in {5, 6})
            adjacent_hard = any(
                0 <= adj < len(plan.plan) and _is_hard(plan.plan[adj])
                for adj in (index - 1, index + 1)
            )
            return (enough_time, weekend, int(not adjacent_hard))

        return max(preferred_indexes, key=score)

    def describe(self, ctx):
        preferred_weekdays = sorted(self._preferred_weekdays(ctx))
        if preferred_weekdays:
            return (
                f"long_run 은 선호 long_run 요일({preferred_weekdays}) 중 "
                "계획 범위에 있는 날짜에만 배치합니다."
            )
        return "long_run 선호 요일이 지정되어 있으면 해당 가용 요일에 배치합니다."


class NoBackToBackQuality:
    """연속된 두 날 모두 quality/long_run 이면 뒷날을 recovery 로."""

    rule_id = "no_back_to_back_quality"
    severity: Severity = "block"

    def check(self, plan, ctx):
        out: list[Violation] = []
        for i in range(1, len(plan.plan)):
            if _is_hard(plan.plan[i]) and _is_hard(plan.plan[i - 1]):
                target_index = i - 1 if plan.plan[i].session_type == "long_run" else i
                out.append(
                    Violation(
                        rule_id=self.rule_id,
                        severity=self.severity,
                        message=(
                            f"back-to-back hard sessions day {i-1}→{i}; "
                            f"demoting day {target_index}"
                        ),
                        day_index=target_index,
                    )
                )
        return out

    def correct(self, plan, ctx, violations):
        for v in violations:
            if v.day_index is None:
                continue
            day = plan.plan[v.day_index]
            new_day = _rebuild_day(day, "recovery", ctx.pace_zones)
            plan = _replace_day(plan, v.day_index, new_day)
        return plan

    def describe(self, ctx):
        return "quality/long_run 세션 사이 최소 1일 간격을 둡니다."


class NoQualityAfterLongRun:
    """long_run 다음 날 quality 금지."""

    rule_id = "no_quality_after_long_run"
    severity: Severity = "block"

    def check(self, plan, ctx):
        out: list[Violation] = []
        for i in range(1, len(plan.plan)):
            prev_long = plan.plan[i - 1].session_type == "long_run"
            curr_quality = plan.plan[i].session_type == "quality"
            if prev_long and curr_quality:
                out.append(
                    Violation(
                        rule_id=self.rule_id,
                        severity=self.severity,
                        message=f"quality on day {i} follows long_run; demoting to recovery",
                        day_index=i,
                    )
                )
        return out

    def correct(self, plan, ctx, violations):
        for v in violations:
            if v.day_index is None:
                continue
            day = plan.plan[v.day_index]
            new_day = _rebuild_day(day, "recovery", ctx.pace_zones)
            plan = _replace_day(plan, v.day_index, new_day)
        return plan

    def describe(self, ctx):
        return "장거리 세션 다음 날은 quality 를 배치하지 않습니다."


class Quality48hSpacing:
    """모든 quality/long_run 쌍이 최소 48h (=2일) 간격.

    연속일(i, i+1)은 NoBackToBackQuality 가 처리.
    여기선 (i, i+2) 등 비연속 근접 케이스 중 48h 미만을 잡는다.
    (날 단위 계산으로는 i+1 이 NoBackToBackQuality 와 중복이므로
     i+1 케이스는 NoBackToBackQuality 가 이미 처리했다고 가정.
     이 룰은 동일 패스에서 혹시 놓친 쌍을 catch 한다.)
    """

    rule_id = "quality_48h_spacing"
    severity: Severity = "block"

    def check(self, plan, ctx):
        hard_idx = [i for i, d in enumerate(plan.plan) if _is_hard(d)]
        out: list[Violation] = []
        for a, b in zip(hard_idx, hard_idx[1:]):
            if b - a < 2:
                target_index = a if plan.plan[b].session_type == "long_run" else b
                # NoBackToBackQuality 가 i=b 인 경우 처리하므로 여기선 추가만
                out.append(
                    Violation(
                        rule_id=self.rule_id,
                        severity=self.severity,
                        message=(
                            f"hard sessions {a} and {b} within 48h; " f"demoting {target_index}"
                        ),
                        day_index=target_index,
                    )
                )
        return out

    def correct(self, plan, ctx, violations):
        for v in violations:
            if v.day_index is None:
                continue
            day = plan.plan[v.day_index]
            new_day = _rebuild_day(day, "recovery", ctx.pace_zones)
            plan = _replace_day(plan, v.day_index, new_day)
        return plan

    def describe(self, ctx):
        return "quality/long_run 세션 사이 최소 48시간 간격을 보장합니다."


class WeeklyHardCap:
    """주간 hard (quality + long_run) ≤ 2."""

    rule_id = "weekly_hard_cap"
    severity: Severity = "block"

    def check(self, plan, ctx):
        hard_idx = [i for i, d in enumerate(plan.plan) if _is_hard(d)]
        if len(hard_idx) <= 2:
            return []
        # 3번째 이후만 violation; 2번째까지는 유지
        out: list[Violation] = []
        for i in hard_idx[2:]:
            out.append(
                Violation(
                    rule_id=self.rule_id,
                    severity=self.severity,
                    message=f"hard session count > 2; demoting day {i}",
                    day_index=i,
                )
            )
        return out

    def correct(self, plan, ctx, violations):
        for v in violations:
            if v.day_index is None:
                continue
            day = plan.plan[v.day_index]
            new_day = _rebuild_day(day, "base", ctx.pace_zones)
            plan = _replace_day(plan, v.day_index, new_day)
        return plan

    def describe(self, ctx):
        return "주간 hard(quality+long_run) 세션은 최대 2회입니다."


class RespectUnavailability:
    """availability.is_available == False 인 요일은 rest."""

    rule_id = "respect_unavailability"
    severity: Severity = "block"

    def check(self, plan, ctx):
        out: list[Violation] = []
        for i, day in enumerate(plan.plan):
            slot = ctx.availability_for(day.date.weekday())
            if not slot.is_available and day.session_type != "rest":
                out.append(
                    Violation(
                        rule_id=self.rule_id,
                        severity=self.severity,
                        message=f"day {i} ({day.date}) marked unavailable; forcing rest",
                        day_index=i,
                    )
                )
        return out

    def correct(self, plan, ctx, violations):
        for v in violations:
            if v.day_index is None:
                continue
            day = plan.plan[v.day_index]
            new_day = _rebuild_day(day, "rest", ctx.pace_zones)
            plan = _replace_day(plan, v.day_index, new_day)
        return plan

    def describe(self, ctx):
        return "불가 요일에는 rest 를 배치합니다."


class MinOneRestPerWeek:
    """주간 rest ≥ 1."""

    rule_id = "min_one_rest_per_week"
    severity: Severity = "block"

    def check(self, plan, ctx):
        rest_count = sum(1 for d in plan.plan if d.session_type == "rest")
        if rest_count >= 1:
            return []
        return [
            Violation(
                rule_id=self.rule_id,
                severity=self.severity,
                message="zero rest days in 7; inserting rest",
                day_index=None,
            )
        ]

    def correct(self, plan, ctx, violations):
        # 가장 쉬운 non-hard 날을 rest 로. base 우선, 그 다음 recovery.
        candidates = [i for i, d in enumerate(plan.plan) if d.session_type == "base"]
        if not candidates:
            candidates = [i for i, d in enumerate(plan.plan) if d.session_type == "recovery"]
        if not candidates:
            # 전부 hard 거나 rest 인데 rest 가 0인 경우 — 중간 hard 하나 변환
            candidates = [i for i, d in enumerate(plan.plan) if d.session_type == "quality"]
        if not candidates:
            return plan
        # long_run 에서 가장 먼 index 선택
        long_idx = next((i for i, d in enumerate(plan.plan) if d.session_type == "long_run"), 0)
        target = max(candidates, key=lambda i: abs(i - long_idx))
        new_day = _rebuild_day(plan.plan[target], "rest", ctx.pace_zones)
        return _replace_day(plan, target, new_day)

    def describe(self, ctx):
        return "주간 최소 1일 휴식을 보장합니다."


class AcwrCap:
    """주간 계획 러닝 km / chronic_weekly > 1.5 → duration 균등 축소.

    chronic_ewma_load 는 일일 평균(km/day)이므로 주간 비교를 위해 ×7 한다.
    """

    rule_id = "acwr_cap"
    severity: Severity = "block"
    TARGET_RATIO = 1.4
    CAP_RATIO = 1.5

    @staticmethod
    def _chronic_weekly(ctx: "CoachingContext") -> float:
        return float(ctx.scores.chronic_ewma_load) * 7.0

    def check(self, plan, ctx):
        chronic_weekly = self._chronic_weekly(ctx)
        if chronic_weekly <= 0.1:
            return []
        planned_km = _total_planned_km(plan, ctx.pace_zones)
        ratio = planned_km / chronic_weekly
        if ratio <= self.CAP_RATIO:
            return []
        return [
            Violation(
                rule_id=self.rule_id,
                severity=self.severity,
                message=(
                    f"ACWR {ratio:.2f} (planned {planned_km:.1f}km vs chronic "
                    f"{chronic_weekly:.1f}km/wk) > {self.CAP_RATIO}"
                ),
                day_index=None,
            )
        ]

    def correct(self, plan, ctx, violations):
        chronic_weekly = self._chronic_weekly(ctx)
        if chronic_weekly <= 0.1:
            return plan
        planned_km = _total_planned_km(plan, ctx.pace_zones)
        if planned_km <= 0:
            return plan
        current_ratio = planned_km / chronic_weekly
        if current_ratio <= self.TARGET_RATIO:
            return plan

        # 1단계: 필요시 구조적 축소를 반복 — 가장 긴 base/recovery 를 rest 로 전환.
        # step 의 60s 하한 때문에 scale-only 로는 수렴 불가한 경우가 있어,
        # CAP_RATIO 안으로 들어오거나 변환 대상이 떨어질 때까지 반복.
        structural_plan = plan
        current_km = planned_km
        while current_km / chronic_weekly > self.CAP_RATIO:
            reduced = self._convert_longest_to_rest(structural_plan, ctx)
            if reduced is structural_plan:
                break  # 더 줄일 대상 없음
            structural_plan = reduced
            current_km = _total_planned_km(structural_plan, ctx.pace_zones)

        # 2단계: 남은 날들에 대해 duration 스케일링으로 미세 조정.
        current_ratio = current_km / chronic_weekly
        if current_ratio <= self.TARGET_RATIO:
            return structural_plan
        scale = self.TARGET_RATIO / current_ratio  # < 1
        new_days = []
        for day in structural_plan.plan:
            if day.session_type == "rest":
                new_days.append(day)
                continue
            new_steps = []
            for s in day.workout.steps:
                new_dur = max(60, int(s.duration_value * scale))
                new_steps.append(
                    _build_step(
                        s.type,
                        new_dur,
                        s.target_value or "0:00",
                        target_type=s.target_type,
                    )
                )
            new_workout = day.workout.model_copy(update={"steps": new_steps})
            new_minutes = sum(s.duration_value for s in new_steps) // 60
            new_days.append(
                day.model_copy(update={"workout": new_workout, "planned_minutes": new_minutes})
            )
        return structural_plan.model_copy(update={"plan": new_days})

    @staticmethod
    def _convert_longest_to_rest(plan, ctx):
        """base/recovery 중 가장 긴 하루를 rest 로 (long_run / quality 는 보존).

        base/recovery 가 모두 소진됐으면 원본 그대로 반환 — quality 나 long_run 을
        희생해서 ACWR 를 맞추진 않는다 (상위 룰이 다른 방식으로 보정).
        """
        candidates = [
            (i, d.workout.total_duration)
            for i, d in enumerate(plan.plan)
            if d.session_type in ("base", "recovery")
        ]
        if not candidates:
            return plan
        target_idx = max(candidates, key=lambda t: t[1])[0]
        new_day = _rebuild_day(plan.plan[target_idx], "rest", ctx.pace_zones)
        return _replace_day(plan, target_idx, new_day)

    def describe(self, ctx):
        chronic_weekly = self._chronic_weekly(ctx)
        if chronic_weekly > 0:
            cap_km = chronic_weekly * self.CAP_RATIO
            return (
                f"주간 총 러닝량은 {cap_km:.0f}km 이하여야 합니다 "
                f"(chronic {chronic_weekly:.1f}km/wk 기준 ACWR ≤ {self.CAP_RATIO})."
            )
        return "주간 러닝량의 ACWR(acute:chronic) 를 1.5 이하로 유지합니다."


class MaxDurationPerDay:
    """day duration > availability.max_duration_minutes → step 비례 축소."""

    rule_id = "max_duration_per_day"
    severity: Severity = "block"

    def check(self, plan, ctx):
        out: list[Violation] = []
        for i, day in enumerate(plan.plan):
            slot = ctx.availability_for(day.date.weekday())
            cap = slot.max_duration_minutes
            if cap is None or cap <= 0:
                continue
            if day.workout.total_duration_minutes > cap:
                out.append(
                    Violation(
                        rule_id=self.rule_id,
                        severity=self.severity,
                        message=(
                            f"day {i} duration {day.workout.total_duration_minutes}m"
                            f" > cap {cap}m"
                        ),
                        day_index=i,
                    )
                )
        return out

    def correct(self, plan, ctx, violations):

        for v in violations:
            if v.day_index is None:
                continue
            day = plan.plan[v.day_index]
            slot = ctx.availability_for(day.date.weekday())
            cap = slot.max_duration_minutes or day.workout.total_duration_minutes
            current = day.workout.total_duration_minutes
            if current <= cap:
                continue
            scale = cap / current
            new_steps = []
            for s in day.workout.steps:
                new_dur = max(60, int(s.duration_value * scale))
                new_steps.append(
                    _build_step(
                        s.type,
                        new_dur,
                        s.target_value or "0:00",
                        target_type=s.target_type,
                    )
                )
            new_workout = day.workout.model_copy(update={"steps": new_steps})
            new_minutes = sum(s.duration_value for s in new_steps) // 60
            new_day = day.model_copy(
                update={"workout": new_workout, "planned_minutes": new_minutes}
            )
            plan = _replace_day(plan, v.day_index, new_day)
        return plan

    def describe(self, ctx):
        return "요일별 max 시간 캡을 초과하지 않도록 steps 를 축소합니다."


class NonRestHasSteps:
    """non-rest 인데 steps 가 비었거나 총 duration 이 0 → 기본 steps 주입."""

    rule_id = "non_rest_has_steps"
    severity: Severity = "block"

    def check(self, plan, ctx):
        out: list[Violation] = []
        for i, day in enumerate(plan.plan):
            if day.session_type == "rest":
                continue
            if not day.workout.steps or day.workout.total_duration <= 0:
                out.append(
                    Violation(
                        rule_id=self.rule_id,
                        severity=self.severity,
                        message=f"non-rest day {i} has no valid steps; injecting defaults",
                        day_index=i,
                    )
                )
        return out

    def correct(self, plan, ctx, violations):
        for v in violations:
            if v.day_index is None:
                continue
            day = plan.plan[v.day_index]
            new_day = _rebuild_day(day, day.session_type or "base", ctx.pace_zones)
            plan = _replace_day(plan, v.day_index, new_day)
        return plan

    def describe(self, ctx):
        return "rest 가 아닌 날은 반드시 실행 가능한 steps 를 포함합니다."


class MinStepDuration:
    """step.duration_value ≤ 0 → 60 초."""

    rule_id = "min_step_duration"
    severity: Severity = "block"

    def check(self, plan, ctx):
        out: list[Violation] = []
        for i, day in enumerate(plan.plan):
            for j, s in enumerate(day.workout.steps):
                if s.duration_value <= 0:
                    out.append(
                        Violation(
                            rule_id=self.rule_id,
                            severity=self.severity,
                            message=f"day {i} step {j} zero duration; setting 60s",
                            day_index=i,
                        )
                    )
                    break  # day 단위 identity 로 dedupe
        return out

    def correct(self, plan, ctx, violations):

        for v in violations:
            if v.day_index is None:
                continue
            day = plan.plan[v.day_index]
            new_steps = [
                _build_step(
                    s.type,
                    max(60, s.duration_value),
                    s.target_value or "0:00",
                    target_type=s.target_type,
                )
                for s in day.workout.steps
            ]
            new_workout = day.workout.model_copy(update={"steps": new_steps})
            new_day = day.model_copy(update={"workout": new_workout})
            plan = _replace_day(plan, v.day_index, new_day)
        return plan

    def describe(self, ctx):
        return "각 step duration 은 최소 60초입니다."


class PaceBandIntegrity:
    """step pace 가 선수의 pace safety band 밖이면 해당 스텝만 경계값으로 보정.

    어느 band 안에서 정확히 어떤 페이스를 쓸지는 LLM(코치)이 결정한다. 이 룰은
    위험하게 빠르거나 느린 페이스만 차단하는 hard bound 역할을 한다.
    """

    rule_id = "pace_band_integrity"
    severity: Severity = "warn"

    def check(self, plan, ctx):
        out: list[Violation] = []
        for i, day in enumerate(plan.plan):
            for j, s in enumerate(day.workout.steps):
                if s.target_type != "speed":
                    continue
                parsed = _pace_seconds(s.target_value or "")
                band = _pace_band_for_step(ctx, s.type, day.session_type or "base")
                if parsed is None:
                    out.append(
                        Violation(
                            rule_id=self.rule_id,
                            severity=self.severity,
                            message=f"day {i} step {j} unparseable pace '{s.target_value}'",
                            day_index=i,
                        )
                    )
                    break
                if not _pace_within_band(parsed, band):
                    out.append(
                        Violation(
                            rule_id=self.rule_id,
                            severity=self.severity,
                            message=(
                                f"day {i} step {j} ({s.type}) pace "
                                f"{s.target_value} outside safety band {band.fast}-{band.slow}"
                            ),
                            day_index=i,
                        )
                    )
                    break
        return out

    def correct(self, plan, ctx, violations):
        for v in violations:
            if v.day_index is None:
                continue
            day = plan.plan[v.day_index]
            old_steps = day.workout.steps
            new_steps = []
            description = day.workout.description or ""

            for s in old_steps:
                if s.target_type != "speed":
                    new_steps.append(s)
                    continue
                parsed = _pace_seconds(s.target_value or "")
                band = _pace_band_for_step(ctx, s.type, day.session_type or "base")
                if parsed is not None and _pace_within_band(parsed, band):
                    new_steps.append(s)
                    continue
                fallback_pace = _pace_for_step(ctx.pace_zones, s.type, day.session_type or "base")
                fallback_seconds = _pace_seconds(fallback_pace) or _pace_seconds(band.slow) or 420
                corrected_pace = _clamp_pace_to_band(parsed or fallback_seconds, band)
                old_pace = s.target_value or ""
                if old_pace and old_pace != corrected_pace and _PACE_RE.fullmatch(old_pace.strip()):
                    description = description.replace(old_pace, corrected_pace)
                new_steps.append(_build_step(s.type, s.duration_value, corrected_pace))

            new_workout = day.workout.model_copy(
                update={"steps": new_steps, "description": description}
            )
            new_day = day.model_copy(update={"workout": new_workout})
            plan = _replace_day(plan, v.day_index, new_day)
        return plan

    def describe(self, ctx):
        return (
            "각 step pace 는 선수의 pace safety band 안에서 선택하세요. "
            "밴드 안의 구체 페이스는 세션 의도와 선수 상태에 맞춰 결정할 수 있습니다."
        )


PaceZoneIntegrity = PaceBandIntegrity


class StandardizeWorkoutName:
    """workout.workout_name 을 session_type 기반 영문 표준 이름으로 강제.

    Garmin 앱과 기존 워크아웃 제목 convention 일치를 위해 LLM 이 자유 작명한
    "휴식 및 회복", "전략적 휴식" 같은 것을 덮어쓴다. quality 세션은 step 구성
    (Interval 포함)에 따라 'Interval' 로 네이밍.
    """

    rule_id = "standardize_workout_name"
    severity: Severity = "warn"

    _STANDARD = {
        "rest": "Rest Day",
        "recovery": "Recovery Run",
        "base": "Base Run",
        "long_run": "Long Run",
    }

    @classmethod
    def _expected_name(cls, day, ctx=None) -> str:
        if day.session_type != "quality":
            return cls._STANDARD.get(day.session_type or "base", "Base Run")
        continuous_name = cls._continuous_interval_name(day, ctx)
        if continuous_name:
            return continuous_name
        workout_type = str(day.workout_type)
        if workout_type in {"Interval", "Threshold", "Tempo Run", "Fartlek"}:
            return workout_type
        return cls._classify_quality(day, ctx)

    @staticmethod
    def _continuous_interval_name(day, ctx=None) -> str | None:
        """LLM이 continuous quality block을 Interval step으로 낸 경우 보정."""
        if ctx is None:
            return None
        interval_steps = [s for s in day.workout.steps if s.type == "Interval"]
        if len(interval_steps) != 1:
            return None
        step = interval_steps[0]
        if step.duration_value < 600:
            return None
        pace_sec = _pace_seconds(step.target_value or "")
        if pace_sec is None:
            return None
        zones = ctx.pace_zones.to_dict()
        threshold_sec = _pace_seconds(zones.get("threshold", ""))
        if threshold_sec is not None and abs(pace_sec - threshold_sec) <= 5:
            return "Threshold"
        tempo_sec = _pace_seconds(zones.get("tempo", ""))
        if tempo_sec is not None and abs(pace_sec - tempo_sec) <= 5:
            return "Tempo Run"
        return None

    @classmethod
    def _classify_quality(cls, day, ctx=None) -> str:
        """quality 세션의 step 구성·페이스로 구체 훈련 종류를 판별."""
        steps = day.workout.steps
        interval_steps = [s for s in steps if s.type == "Interval"]
        if interval_steps:
            continuous_name = cls._continuous_interval_name(day, ctx)
            if continuous_name:
                return continuous_name
            # Fartlek: Interval duration 이 서로 다르게 섞였으면 (1.5배 이상 차이)
            if len(interval_steps) >= 2:
                durations = [s.duration_value for s in interval_steps]
                if max(durations) > min(durations) * 1.5:
                    return "Fartlek"
            return "Interval"

        # Interval 없는 continuous quality: pace 로 Threshold vs Tempo 구분
        run_steps = [s for s in steps if s.type == "Run"]
        if not run_steps or ctx is None:
            return "Tempo Run"
        zones = ctx.pace_zones.to_dict()
        threshold_sec = _pace_seconds(zones.get("threshold", "5:00"))
        if threshold_sec is None:
            return "Tempo Run"
        longest = max(run_steps, key=lambda s: s.duration_value)
        longest_pace = _pace_seconds(longest.target_value or "")
        if longest_pace is None:
            return "Tempo Run"
        # threshold ± 5s 면 Threshold 세션
        if abs(longest_pace - threshold_sec) <= 5:
            return "Threshold"
        return "Tempo Run"

    @classmethod
    def _normalized_steps(cls, day, ctx):
        expected = cls._expected_name(day, ctx)
        if expected not in {"Threshold", "Tempo Run"}:
            return day.workout.steps
        if not cls._continuous_interval_name(day, ctx):
            return day.workout.steps
        return [
            (
                _build_step(
                    "Run",
                    s.duration_value,
                    s.target_value or "0:00",
                    target_type=s.target_type,
                )
                if s.type == "Interval"
                else s
            )
            for s in day.workout.steps
        ]

    def check(self, plan, ctx):
        out: list[Violation] = []
        for i, day in enumerate(plan.plan):
            expected = self._expected_name(day, ctx)
            normalized_steps = self._normalized_steps(day, ctx)
            steps_changed = normalized_steps != day.workout.steps
            type_changed = day.workout_type != expected
            if day.workout.workout_name != expected or type_changed or steps_changed:
                out.append(
                    Violation(
                        rule_id=self.rule_id,
                        severity=self.severity,
                        message=(
                            f"day {i} workout name '{day.workout.workout_name}' " f"→ '{expected}'"
                        ),
                        day_index=i,
                    )
                )
        return out

    def correct(self, plan, ctx, violations):
        for v in violations:
            if v.day_index is None:
                continue
            day = plan.plan[v.day_index]
            expected = self._expected_name(day, ctx)
            new_workout = day.workout.model_copy(
                update={"workout_name": expected, "steps": self._normalized_steps(day, ctx)}
            )
            new_day = day.model_copy(update={"workout": new_workout, "workout_type": expected})
            plan = _replace_day(plan, v.day_index, new_day)
        return plan

    def describe(self, ctx):
        return (
            "workoutName 은 session_type 에 맞춰 'Rest Day', 'Recovery Run', "
            "'Base Run', 'Interval', 'Threshold', 'Tempo Run', 'Fartlek', "
            "'Long Run' 중 하나만 사용하세요 (step 구조와 페이스로 자동 분류)."
        )


class PlanStartsToday:
    """plan[0].date == ctx.today 보장; 벗어나면 전체 날짜를 오늘 기준으로 rebase.

    LLM 이 엉뚱한 시작일을 내놓아도 Garmin 에 잘못 업로드되지 않도록 방어.
    """

    rule_id = "plan_starts_today"
    severity: Severity = "block"

    def check(self, plan, ctx):
        if not plan.plan:
            return []
        if plan.plan[0].date == ctx.today:
            return []
        return [
            Violation(
                rule_id=self.rule_id,
                severity=self.severity,
                message=(
                    f"plan starts {plan.plan[0].date.isoformat()} but today is "
                    f"{ctx.today.isoformat()}; rebasing"
                ),
                day_index=None,
            )
        ]

    def correct(self, plan, ctx, violations):
        from datetime import timedelta

        new_days = []
        for i, day in enumerate(plan.plan):
            new_days.append(day.model_copy(update={"date": ctx.today + timedelta(days=i)}))
        return plan.model_copy(update={"plan": new_days})

    def describe(self, ctx):
        return f"계획 시작일은 반드시 오늘({ctx.today.isoformat()})이어야 합니다."


# ---------------------------------------------------------------------------
# DEFAULT list — 실행 순서 = 보정 순서
# 구조적(session_type 변경) 룰을 먼저, 볼륨/가용성, step-level 마지막.
# ---------------------------------------------------------------------------


DEFAULT_SAFETY_RULES: list[SafetyRule] = [
    PlanStartsToday(),  # 날짜 정합성 먼저
    InjuryBlockQuality(),
    MaxOneLongRun(),
    PreferLongRunAvailability(),
    NoBackToBackQuality(),
    NoQualityAfterLongRun(),
    Quality48hSpacing(),
    WeeklyHardCap(),
    RespectUnavailability(),
    MinOneRestPerWeek(),
    AcwrCap(),
    MaxDurationPerDay(),
    NonRestHasSteps(),
    InjuryReduceVolume(),
    MinStepDuration(),
    PaceBandIntegrity(),
    StandardizeWorkoutName(),  # 마지막: 구조 변경 다 끝난 후 이름 정규화
]
