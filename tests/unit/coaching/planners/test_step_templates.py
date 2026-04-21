"""StepTemplateEngine + QualitySubtypeSelector 유닛 테스트."""

from __future__ import annotations

from running_coach.coaching.planners.step_templates import (
    QualitySubtypeSelector,
    StepTemplateEngine,
)
from running_coach.core.pace_zones import PaceZones

_ZONES = PaceZones(
    interval="4:30",
    threshold="5:00",
    tempo="5:15",
    base="6:45",
    long_run="6:50",
    recovery="7:20",
    warmup="6:45",
    cooldown="7:10",
)


class TestQualitySubtypeSelector:
    def test_peak_returns_threshold(self):
        assert QualitySubtypeSelector.pick("peak", 80, 10) == "threshold"

    def test_taper_returns_threshold(self):
        assert QualitySubtypeSelector.pick("taper", 70, 10) == "threshold"

    def test_base_phase_returns_tempo(self):
        assert QualitySubtypeSelector.pick("base", 65, 20) == "tempo"

    def test_build_good_shape_returns_interval(self):
        assert QualitySubtypeSelector.pick("build", 75, 20) == "interval"

    def test_build_high_injury_risk_returns_tempo(self):
        assert QualitySubtypeSelector.pick("build", 70, 45) == "tempo"

    def test_build_low_readiness_returns_tempo(self):
        assert QualitySubtypeSelector.pick("build", 45, 20) == "tempo"

    def test_build_moderate_returns_threshold(self):
        assert QualitySubtypeSelector.pick("build", 60, 25) == "threshold"


class TestStepTemplateEngine:
    def test_rest_returns_empty(self):
        steps = StepTemplateEngine.build("rest", 0, _ZONES)
        assert steps == []

    def test_recovery_has_three_steps(self):
        steps = StepTemplateEngine.build("recovery", 30, _ZONES)
        assert len(steps) == 3
        assert steps[0].type == "Warmup"
        assert steps[1].type == "Run"
        assert steps[2].type == "Cooldown"

    def test_recovery_uses_recovery_pace(self):
        steps = StepTemplateEngine.build("recovery", 30, _ZONES)
        assert steps[1].target_value == _ZONES.recovery

    def test_base_has_three_steps(self):
        steps = StepTemplateEngine.build("base", 45, _ZONES)
        assert len(steps) == 3
        assert steps[1].target_value == _ZONES.base

    def test_long_run_uses_long_run_pace(self):
        steps = StepTemplateEngine.build("long_run", 90, _ZONES)
        run = next(s for s in steps if s.type == "Run")
        assert run.target_value == _ZONES.long_run

    def test_interval_has_interval_steps(self):
        steps = StepTemplateEngine.build("quality", 45, _ZONES, "interval")
        interval_steps = [s for s in steps if s.type == "Interval"]
        assert len(interval_steps) >= 4
        # 균일 duration → StandardizeWorkoutName 이 Interval 로 분류
        durations = [s.duration_value for s in interval_steps]
        assert len(set(durations)) == 1

    def test_fartlek_has_varying_interval_durations(self):
        steps = StepTemplateEngine.build("quality", 50, _ZONES, "fartlek")
        interval_steps = [s for s in steps if s.type == "Interval"]
        assert len(interval_steps) >= 3
        durations = [s.duration_value for s in interval_steps]
        # max > min * 1.5 → StandardizeWorkoutName 이 Fartlek 으로 분류
        assert max(durations) > min(durations) * 1.5

    def test_threshold_run_uses_threshold_pace(self):
        steps = StepTemplateEngine.build("quality", 45, _ZONES, "threshold")
        run_steps = [s for s in steps if s.type == "Run"]
        assert any(s.target_value == _ZONES.threshold for s in run_steps)

    def test_tempo_run_uses_tempo_pace(self):
        steps = StepTemplateEngine.build("quality", 45, _ZONES, "tempo")
        run_steps = [s for s in steps if s.type == "Run"]
        assert any(s.target_value == _ZONES.tempo for s in run_steps)

    def test_threshold_splits_into_two_blocks_for_long_session(self):
        # target 60분 → budget 40분 > 20분 → 두 블록
        steps = StepTemplateEngine.build("quality", 60, _ZONES, "threshold")
        run_steps = [s for s in steps if s.type == "Run"]
        assert len(run_steps) == 2

    def test_all_steps_have_positive_duration(self):
        for session_type in ("recovery", "base", "long_run"):
            steps = StepTemplateEngine.build(session_type, 45, _ZONES)
            assert all(s.duration_value > 0 for s in steps)

    def test_unknown_session_type_falls_back_to_base(self):
        steps = StepTemplateEngine.build("unknown", 40, _ZONES)
        assert len(steps) == 3
        run = next(s for s in steps if s.type == "Run")
        assert run.target_value == _ZONES.base
