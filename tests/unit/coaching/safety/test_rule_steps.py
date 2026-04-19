"""NonRestHasSteps + MinStepDuration + PaceZoneIntegrity."""

from __future__ import annotations

from running_coach.coaching.safety.rules import (
    MinStepDuration,
    NonRestHasSteps,
    PaceZoneIntegrity,
)
from running_coach.models.training import DailyPlan, TrainingPlan, Workout

from .conftest import make_day, make_plan, make_step


class TestNonRestHasSteps:
    def test_passes_with_valid_steps(self, healthy_ctx):
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        assert NonRestHasSteps().check(plan, healthy_ctx) == []

    def test_rest_day_with_empty_steps_is_ok(self, healthy_ctx):
        plan = make_plan(["rest", "quality", "base", "base", "base", "long_run", "rest"])
        assert NonRestHasSteps().check(plan, healthy_ctx) == []

    def test_detects_non_rest_with_empty_steps(self, healthy_ctx):
        # Workout.validate_workout 가 non-rest + 빈 steps 를 거부하므로
        # workout_name 에 Rest 를 포함해 우회한 뒤 session_type 을 base 로 override.
        # 이 케이스는 LLM 출력이 꼬였을 때 가능.
        rest_workout = Workout(workout_name="Rest Day", steps=[])
        odd_day = DailyPlan(
            date=make_plan(["base"] * 7).plan[0].date,
            session_type="base",
            planned_minutes=0,
            workout=rest_workout,
        )
        days = make_plan(["rest", "base", "base", "base", "base", "long_run", "rest"]).plan
        days[0] = odd_day
        plan = TrainingPlan(plan=days)
        violations = NonRestHasSteps().check(plan, healthy_ctx)
        assert [v.day_index for v in violations] == [0]

    def test_corrector_injects_default_steps(self, healthy_ctx):
        rule = NonRestHasSteps()
        rest_workout = Workout(workout_name="Rest Day", steps=[])
        odd_day = DailyPlan(
            date=make_plan(["base"] * 7).plan[0].date,
            session_type="base",
            planned_minutes=40,
            workout=rest_workout,
        )
        days = make_plan(["rest", "base", "base", "base", "base", "long_run", "rest"]).plan
        days[0] = odd_day
        plan = TrainingPlan(plan=days)
        violations = rule.check(plan, healthy_ctx)
        fixed = rule.correct(plan, healthy_ctx, violations)
        assert len(fixed.plan[0].workout.steps) > 0
        assert rule.check(fixed, healthy_ctx) == []


class TestMinStepDuration:
    def test_passes_with_positive_durations(self, healthy_ctx):
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        assert MinStepDuration().check(plan, healthy_ctx) == []

    def test_detects_zero_duration_step(self, healthy_ctx):
        # Pydantic WorkoutStep 은 duration_value > 0 이 제약이라 직접 bypass 어려움.
        # 대신 model_copy 로 세팅 후 __dict__ 를 통해 강제 수정.
        plan = make_plan(["base", "base", "base", "base", "base", "long_run", "rest"])
        # validate 이후에 강제로 0 으로 세팅
        bad_step = plan.plan[0].workout.steps[0]
        object.__setattr__(bad_step, "duration_value", 0)
        violations = MinStepDuration().check(plan, healthy_ctx)
        assert len(violations) == 1
        assert violations[0].day_index == 0

    def test_corrector_sets_60_seconds(self, healthy_ctx):
        rule = MinStepDuration()
        plan = make_plan(["base", "base", "base", "base", "base", "long_run", "rest"])
        bad_step = plan.plan[0].workout.steps[0]
        object.__setattr__(bad_step, "duration_value", 0)
        violations = rule.check(plan, healthy_ctx)
        fixed = rule.correct(plan, healthy_ctx, violations)
        assert all(s.duration_value >= 60 for s in fixed.plan[0].workout.steps)
        assert rule.check(fixed, healthy_ctx) == []


class TestPaceZoneIntegrity:
    def test_passes_with_zone_paces(self, healthy_ctx):
        plan = make_plan(["base", "quality", "base", "base", "base", "long_run", "rest"])
        assert PaceZoneIntegrity().check(plan, healthy_ctx) == []

    def test_detects_pace_outside_zones(self, healthy_ctx):
        # Run step 에 3:30 (interval 보다 빠른) 페이스 주입
        fast_step = make_step("Run", 1800, "3:30")
        days = make_plan(["base"] * 6 + ["rest"]).plan
        days[0] = make_day(
            days[0].date,
            "base",
            steps=[
                make_step("Warmup", 600, "6:45"),
                fast_step,
                make_step("Cooldown", 300, "7:10"),
            ],
        )
        plan = TrainingPlan(plan=days)
        violations = PaceZoneIntegrity().check(plan, healthy_ctx)
        assert any(v.day_index == 0 for v in violations)

    def test_corrector_overwrites_with_zone_pace(self, healthy_ctx):
        rule = PaceZoneIntegrity()
        fast_step = make_step("Run", 1800, "3:30")
        days = make_plan(["base"] * 6 + ["rest"]).plan
        days[0] = make_day(
            days[0].date,
            "base",
            steps=[
                make_step("Warmup", 600, "6:45"),
                fast_step,
                make_step("Cooldown", 300, "7:10"),
            ],
        )
        plan = TrainingPlan(plan=days)
        violations = rule.check(plan, healthy_ctx)
        fixed = rule.correct(plan, healthy_ctx, violations)
        # Run step pace 이 base zone (6:45) 으로 덮어써짐
        assert fixed.plan[0].workout.steps[1].target_value == "6:45"
        assert rule.check(fixed, healthy_ctx) == []
