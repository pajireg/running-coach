from datetime import date

from running_coach.core.pace_zones import PaceZoneEngine
from running_coach.models.config import RaceConfig
from running_coach.models.context import ActivityContext
from running_coach.models.health import HealthMetrics
from running_coach.models.metrics import AdvancedMetrics
from running_coach.models.performance import (
    LactateThreshold,
    PerformanceMetrics,
    PersonalRecord,
)


def _metrics(performance: PerformanceMetrics) -> AdvancedMetrics:
    return AdvancedMetrics(
        date=date(2026, 4, 19),
        health=HealthMetrics(),
        performance=performance,
        context=ActivityContext(),
    )


def test_pace_zone_engine_prefers_lactate_threshold_pace():
    zones = PaceZoneEngine.calculate(
        _metrics(
            PerformanceMetrics(
                lactate_threshold=LactateThreshold(pace="4:55/km", heart_rate=176)
            )
        ),
        RaceConfig(),
    )

    assert zones.interval == "4:30"
    assert zones.threshold == "5:00"
    assert zones.tempo == "5:15"
    assert zones.base == "6:45"
    assert zones.long_run == "6:40"
    assert zones.recovery == "7:20"


def test_pace_zone_engine_falls_back_to_personal_records():
    zones = PaceZoneEngine.calculate(
        _metrics(
            PerformanceMetrics(
                personal_records=[
                    PersonalRecord(type="10K", time_seconds=3000, formatted_time="50m 00s")
                ]
            )
        ),
        RaceConfig(),
    )

    assert zones.threshold == "5:13"
    assert zones.base == "6:58"


def test_pace_zone_engine_uses_race_target_when_no_lt_available():
    zones = PaceZoneEngine.calculate(
        _metrics(PerformanceMetrics()),
        RaceConfig(target_pace="4:54"),
    )

    assert zones.threshold == "4:59"
    assert zones.interval == "4:29"
