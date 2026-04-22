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


@dataclass(frozen=True)
class PaceBand:
    """Allowed pace range for an LLM-selected workout target.

    Values are MM:SS/km strings. ``fast`` is the faster boundary and ``slow`` is
    the slower boundary.
    """

    fast: str
    slow: str

    def to_dict(self) -> dict[str, str]:
        return {"fast": self.fast, "slow": self.slow}


@dataclass(frozen=True)
class PaceCapabilityProfile:
    """Evidence and safety bounds for LLM pace prescription.

    ``zones`` keeps deterministic center paces for legacy planning and fallback
    corrections. ``bands`` is the contract used by ``llm_driven``: the LLM may
    choose any pace inside the relevant band.
    """

    threshold_seconds: int
    threshold_basis: str
    zones: PaceZones
    bands: dict[str, PaceBand]

    def to_prompt_dict(self) -> dict[str, object]:
        return {
            "thresholdEstimate": PaceZoneEngine._format_pace(self.threshold_seconds),
            "thresholdBasis": self.threshold_basis,
            "referenceCenters": self.zones.to_dict(),
            "safetyBands": {key: band.to_dict() for key, band in sorted(self.bands.items())},
        }

    def band_for_step(self, step_type: str, session_type: str) -> PaceBand:
        key = self._band_key_for_step(step_type, session_type)
        return self.bands[key]

    @classmethod
    def from_zones(
        cls,
        zones: PaceZones,
        threshold_seconds: Optional[int] = None,
        threshold_basis: str = "unknown",
    ) -> "PaceCapabilityProfile":
        threshold = threshold_seconds or PaceZoneEngine._pace_to_seconds(zones.threshold) or 295
        return cls(
            threshold_seconds=threshold,
            threshold_basis=threshold_basis,
            zones=zones,
            bands=PaceZoneEngine._bands_from_zones(zones),
        )

    @staticmethod
    def _band_key_for_step(step_type: str, session_type: str) -> str:
        if step_type == "Warmup":
            return "recovery" if session_type == "recovery" else "warmup"
        if step_type == "Cooldown":
            return "cooldown"
        if step_type == "Recovery":
            return "recovery"
        if step_type == "Interval":
            return "interval"
        if session_type == "recovery":
            return "recovery"
        if session_type == "long_run":
            return "longRun"
        if session_type == "quality":
            return "qualityContinuous"
        return "base"


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
        threshold_seconds, _ = cls._threshold_profile(metrics, race_config)
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
    def profile(
        cls,
        metrics: AdvancedMetrics,
        race_config: RaceConfig,
    ) -> PaceCapabilityProfile:
        """Build pace evidence and safety bands for LLM prescription."""
        threshold_seconds, basis = cls._threshold_profile(metrics, race_config)
        zones = cls.calculate(metrics, race_config)
        return PaceCapabilityProfile(
            threshold_seconds=threshold_seconds,
            threshold_basis=basis,
            zones=zones,
            bands=cls._bands_from_zones(zones),
        )

    @classmethod
    def _threshold_seconds(cls, metrics: AdvancedMetrics, race_config: RaceConfig) -> int:
        threshold_seconds, _ = cls._threshold_profile(metrics, race_config)
        return threshold_seconds

    @classmethod
    def _threshold_profile(
        cls,
        metrics: AdvancedMetrics,
        race_config: RaceConfig,
    ) -> tuple[int, str]:
        lt_pace = (
            metrics.performance.lactate_threshold.pace
            if metrics.performance.lactate_threshold
            else None
        )
        parsed_lt = cls._pace_to_seconds(lt_pace)
        if parsed_lt is not None:
            return parsed_lt, "garmin_lactate_threshold"

        race_target = cls._pace_to_seconds(race_config.target_pace)
        if race_target is not None:
            return race_target, "race_target_pace"

        pr_estimates = [
            estimate
            for pr in metrics.performance.personal_records
            if (estimate := cls._threshold_from_pr(pr)) is not None
        ]
        if pr_estimates:
            return min(pr_estimates), "personal_record_estimate"

        return cls.DEFAULT_THRESHOLD_SECONDS, "conservative_default"

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

    @classmethod
    def _bands_from_zones(cls, zones: PaceZones) -> dict[str, PaceBand]:
        margins = {
            "interval": 25,
            "threshold": 20,
            "tempo": 25,
            "qualityContinuous": 35,
            "base": 45,
            "longRun": 50,
            "recovery": 70,
            "warmup": 70,
            "cooldown": 80,
        }
        centers = {
            **zones.to_dict(),
            "qualityContinuous": zones.tempo,
        }
        bands: dict[str, PaceBand] = {}
        for key, center in centers.items():
            center_seconds = cls._pace_to_seconds(center) or cls.DEFAULT_THRESHOLD_SECONDS
            margin = margins[key]
            bands[key] = PaceBand(
                fast=cls._format_pace(center_seconds - margin),
                slow=cls._format_pace(center_seconds + margin),
            )
        return bands
