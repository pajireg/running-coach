"""Personalized pace-zone calculation for workout generation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from ..models.config import RaceConfig
from ..models.metrics import AdvancedMetrics
from ..models.performance import PersonalRecord


@dataclass(frozen=True)
class PaceZones:
    """Single target pace per workout intent.

    Garmin receives a target pace plus a session-specific margin, so these values
    represent the center of each zone rather than hard limits.
    """

    interval: str
    threshold: str
    tempo: str
    base: str
    long_run: str
    recovery: str
    warmup: str
    cooldown: str

    def for_step(self, step_type: str, session_type: str) -> str:
        if step_type == "Warmup":
            # recovery 세션: warmup(LT+125) < recovery run(LT+145)이므로 recovery pace 사용
            if session_type == "recovery":
                return self.recovery
            # 그 외: warmup(LT+125) > base/long_run(LT+105~110) — 표준 warmup 존 사용
            return self.warmup
        if step_type == "Cooldown":
            return self.cooldown
        if step_type == "Recovery":
            return self.recovery
        if step_type == "Interval":
            return self.interval
        if session_type == "recovery":
            return self.recovery
        if session_type == "long_run":
            return self.long_run
        if session_type == "quality":
            return self.tempo
        return self.base

    def to_dict(self) -> dict[str, str]:
        return {
            "interval": self.interval,
            "threshold": self.threshold,
            "tempo": self.tempo,
            "base": self.base,
            "longRun": self.long_run,
            "recovery": self.recovery,
            "warmup": self.warmup,
            "cooldown": self.cooldown,
        }


class PaceZoneEngine:
    """Derive workout paces from LT pace, PRs, or race goal pace."""

    DEFAULT_THRESHOLD_SECONDS = 295
    PR_DISTANCES_KM = {
        "1K": 1.0,
        "MILE": 1.60934,
        "5K": 5.0,
        "10K": 10.0,
        "HALF_MARATHON": 21.0975,
        "MARATHON": 42.195,
    }

    @classmethod
    def calculate(cls, metrics: AdvancedMetrics, race_config: RaceConfig) -> PaceZones:
        threshold_seconds = cls._threshold_seconds(metrics, race_config)
        return PaceZones(
            interval=cls._format_pace(threshold_seconds - 25),
            threshold=cls._format_pace(threshold_seconds + 5),
            tempo=cls._format_pace(threshold_seconds + 20),
            base=cls._format_pace(threshold_seconds + 110),
            long_run=cls._format_pace(threshold_seconds + 105),
            recovery=cls._format_pace(threshold_seconds + 145),
            # Pfitzinger: 워밍업은 easy pace보다 15~30s/km 느림
            warmup=cls._format_pace(threshold_seconds + 125),
            # 쿨다운은 recovery pace (가장 편안한 속도)
            cooldown=cls._format_pace(threshold_seconds + 145),
        )

    @classmethod
    def _threshold_seconds(cls, metrics: AdvancedMetrics, race_config: RaceConfig) -> int:
        lt_pace = (
            metrics.performance.lactate_threshold.pace
            if metrics.performance.lactate_threshold
            else None
        )
        parsed_lt = cls._pace_to_seconds(lt_pace)
        if parsed_lt is not None:
            return parsed_lt

        race_target = cls._pace_to_seconds(race_config.target_pace)
        if race_target is not None:
            return race_target

        pr_estimates = [
            estimate
            for pr in metrics.performance.personal_records
            if (estimate := cls._threshold_from_pr(pr)) is not None
        ]
        if pr_estimates:
            return min(pr_estimates)

        return cls.DEFAULT_THRESHOLD_SECONDS

    @classmethod
    def _threshold_from_pr(cls, pr: PersonalRecord) -> Optional[int]:
        distance = cls.PR_DISTANCES_KM.get(pr.type)
        if not distance or pr.time_seconds <= 0:
            return None
        pace = int(round(pr.time_seconds / distance))
        if pr.type == "1K":
            return pace + 45
        if pr.type == "MILE":
            return pace + 35
        if pr.type == "5K":
            return pace + 20
        if pr.type == "10K":
            return pace + 8
        if pr.type == "HALF_MARATHON":
            return max(180, pace - 5)
        if pr.type == "MARATHON":
            return max(180, pace - 20)
        return None

    @staticmethod
    def _pace_to_seconds(value: Optional[str]) -> Optional[int]:
        if not value:
            return None
        normalized = value.replace("/km", "").strip()
        match = re.fullmatch(r"(\d+):(\d{2})", normalized)
        if not match:
            return None
        return (int(match.group(1)) * 60) + int(match.group(2))

    @staticmethod
    def _format_pace(seconds: int) -> str:
        bounded = max(180, min(seconds, 600))
        return f"{bounded // 60}:{bounded % 60:02d}"
