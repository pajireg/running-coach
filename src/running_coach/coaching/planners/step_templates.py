"""순수 알고리즘 기반 WorkoutStep 생성 — LLM 없음.

session_type + target_minutes + PaceZones → WorkoutStep 리스트.
StandardizeWorkoutName Safety Rule 이 step 구성·페이스로 최종 이름을 결정하므로,
step type 과 pace 선택이 곧 workout 이름을 결정한다.
"""

from __future__ import annotations

from typing import Literal

from ...core.pace_zones import PaceZones
from ...models.training import WorkoutStep

QualitySubtype = Literal["interval", "fartlek", "threshold", "tempo"]


class QualitySubtypeSelector:
    """phase + 컨디션 점수 → quality 세션 세부 종류 결정."""

    @staticmethod
    def pick(phase: str, readiness: float, injury_risk: float) -> QualitySubtype:
        if phase in ("peak", "taper"):
            return "threshold"
        if phase == "base":
            return "tempo"
        # build / maintenance
        if readiness >= 70 and injury_risk < 30:
            return "interval"
        if readiness < 50 or injury_risk >= 40:
            return "tempo"
        return "threshold"


def _step(step_type: str, duration_secs: int, pace: str) -> WorkoutStep:
    return WorkoutStep(
        type=step_type,  # type: ignore[arg-type]
        durationValue=max(60, duration_secs),
        durationUnit="second",
        targetType="speed",
        targetValue=pace,
    )


class StepTemplateEngine:
    """session_type + target_minutes + PaceZones → WorkoutStep 리스트.

    StandardizeWorkoutName 이 step 구조를 보고 최종 workout_name 을 결정하므로
    각 메서드는 해당 이름으로 분류될 수 있는 step 구조를 정확히 생성한다.
    - Interval 포함, 동일 duration → "Interval"
    - Interval 포함, max > min * 1.5 → "Fartlek"
    - Run @ threshold ± 5s → "Threshold"
    - Run @ tempo pace → "Tempo Run"
    """

    _WARMUP = 600   # 10 min
    _COOLDOWN = 300  # 5 min
    _SHORT_WU = 300  # 5 min (recovery 세션)

    @classmethod
    def build(
        cls,
        session_type: str,
        target_minutes: int,
        pace_zones: PaceZones,
        quality_subtype: QualitySubtype = "threshold",
    ) -> list[WorkoutStep]:
        target_secs = target_minutes * 60
        if session_type == "rest":
            return []
        if session_type == "recovery":
            return cls._recovery(target_secs, pace_zones)
        if session_type == "base":
            return cls._base(target_secs, pace_zones)
        if session_type == "long_run":
            return cls._long_run(target_secs, pace_zones)
        if session_type == "quality":
            if quality_subtype == "interval":
                return cls._interval(target_secs, pace_zones)
            if quality_subtype == "fartlek":
                return cls._fartlek(target_secs, pace_zones)
            if quality_subtype == "threshold":
                return cls._threshold(target_secs, pace_zones)
            return cls._tempo(target_secs, pace_zones)
        return cls._base(target_secs, pace_zones)

    @classmethod
    def _recovery(cls, target_secs: int, pz: PaceZones) -> list[WorkoutStep]:
        warmup = cls._SHORT_WU
        cooldown = cls._SHORT_WU
        main = max(600, target_secs - warmup - cooldown)
        return [
            _step("Warmup", warmup, pz.recovery),
            _step("Run", main, pz.recovery),
            _step("Cooldown", cooldown, pz.cooldown),
        ]

    @classmethod
    def _base(cls, target_secs: int, pz: PaceZones) -> list[WorkoutStep]:
        warmup = cls._WARMUP
        cooldown = cls._COOLDOWN
        main = max(900, target_secs - warmup - cooldown)
        return [
            _step("Warmup", warmup, pz.warmup),
            _step("Run", main, pz.base),
            _step("Cooldown", cooldown, pz.cooldown),
        ]

    @classmethod
    def _long_run(cls, target_secs: int, pz: PaceZones) -> list[WorkoutStep]:
        warmup = cls._WARMUP
        cooldown = cls._COOLDOWN
        main = max(2700, target_secs - warmup - cooldown)
        return [
            _step("Warmup", warmup, pz.long_run),
            _step("Run", main, pz.long_run),
            _step("Cooldown", cooldown, pz.cooldown),
        ]

    @classmethod
    def _interval(cls, target_secs: int, pz: PaceZones) -> list[WorkoutStep]:
        """균일 90s 인터벌 → StandardizeWorkoutName 이 "Interval" 로 분류."""
        warmup = cls._WARMUP
        cooldown = cls._WARMUP  # quality 는 10분 쿨다운
        budget = max(600, target_secs - warmup - cooldown)
        rep_secs = 90
        rec_secs = 90
        n_reps = max(4, min(8, budget // (rep_secs + rec_secs)))
        steps: list[WorkoutStep] = [_step("Warmup", warmup, pz.warmup)]
        for _ in range(n_reps):
            steps.append(_step("Interval", rep_secs, pz.interval))
            steps.append(_step("Recovery", rec_secs, pz.recovery))
        steps.append(_step("Cooldown", cooldown, pz.cooldown))
        return steps

    @classmethod
    def _fartlek(cls, target_secs: int, pz: PaceZones) -> list[WorkoutStep]:
        """60s / 120s 교차 → max/min = 2.0 → StandardizeWorkoutName 이 "Fartlek" 분류."""
        warmup = cls._WARMUP
        cooldown = cls._WARMUP
        budget = max(600, target_secs - warmup - cooldown)
        pattern = [60, 120, 60, 120, 60, 120]
        rec_secs = 90
        # 평균 rep 90s + rec 90s = 180s
        n_reps = max(3, min(6, budget // 180))
        steps: list[WorkoutStep] = [_step("Warmup", warmup, pz.warmup)]
        for i in range(n_reps):
            rep = pattern[i % len(pattern)]
            steps.append(_step("Interval", rep, pz.interval))
            steps.append(_step("Recovery", rec_secs, pz.recovery))
        steps.append(_step("Cooldown", cooldown, pz.cooldown))
        return steps

    @classmethod
    def _threshold(cls, target_secs: int, pz: PaceZones) -> list[WorkoutStep]:
        """threshold 페이스 Run → StandardizeWorkoutName 이 "Threshold" 분류."""
        warmup = cls._WARMUP
        cooldown = cls._WARMUP
        budget = max(600, target_secs - warmup - cooldown)
        if budget > 1200:
            # 20분 초과: 두 블록으로 분할 (3분 recovery 사이)
            block1 = int(budget * 0.55)
            block2 = max(300, budget - block1 - 180)
            return [
                _step("Warmup", warmup, pz.warmup),
                _step("Run", block1, pz.threshold),
                _step("Recovery", 180, pz.recovery),
                _step("Run", block2, pz.threshold),
                _step("Cooldown", cooldown, pz.cooldown),
            ]
        return [
            _step("Warmup", warmup, pz.warmup),
            _step("Run", budget, pz.threshold),
            _step("Cooldown", cooldown, pz.cooldown),
        ]

    @classmethod
    def _tempo(cls, target_secs: int, pz: PaceZones) -> list[WorkoutStep]:
        """tempo 페이스 Run → StandardizeWorkoutName 이 "Tempo Run" 분류."""
        warmup = cls._WARMUP
        cooldown = cls._WARMUP
        main = max(900, target_secs - warmup - cooldown)
        return [
            _step("Warmup", warmup, pz.warmup),
            _step("Run", main, pz.tempo),
            _step("Cooldown", cooldown, pz.cooldown),
        ]
