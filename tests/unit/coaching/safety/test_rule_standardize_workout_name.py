"""StandardizeWorkoutName: session_type 기반 영문 표준 이름 강제."""

from __future__ import annotations

from datetime import timedelta

from running_coach.coaching.safety.rules import StandardizeWorkoutName
from running_coach.models.training import TrainingPlan, Workout

from .conftest import make_day, make_plan


class TestStandardizeWorkoutName:
    def test_passes_with_standard_names(self, healthy_ctx):
        plan = make_plan(["base", "quality", "base", "recovery", "base", "long_run", "rest"])
        # conftest default quality → "Interval" (이미 표준)
        assert StandardizeWorkoutName().check(plan, healthy_ctx) == []

    def test_detects_korean_rest_name(self, healthy_ctx):
        rule = StandardizeWorkoutName()
        days = [make_day(healthy_ctx.today + timedelta(days=i), "base") for i in range(7)]
        # workout name에 'rest' 포함(validator 통과)되지만 표준이 아닌 경우.
        odd_rest = Workout(workout_name="Rest 회복일", steps=[])
        days[0] = days[0].model_copy(
            update={"workout": odd_rest, "session_type": "rest", "planned_minutes": 0}
        )
        plan = TrainingPlan(plan=days)
        violations = rule.check(plan, healthy_ctx)
        assert any(v.day_index == 0 for v in violations)

    def test_corrector_renames_non_standard_rest_to_rest_day(self, healthy_ctx):
        rule = StandardizeWorkoutName()
        days = [make_day(healthy_ctx.today + timedelta(days=i), "base") for i in range(7)]
        odd_rest = Workout(workout_name="Rest 회복일", steps=[])
        days[0] = days[0].model_copy(
            update={"workout": odd_rest, "session_type": "rest", "planned_minutes": 0}
        )
        plan = TrainingPlan(plan=days)
        violations = rule.check(plan, healthy_ctx)
        fixed = rule.correct(plan, healthy_ctx, violations)
        assert fixed.plan[0].workout.workout_name == "Rest Day"
        assert rule.check(fixed, healthy_ctx) == []

    def test_quality_without_interval_becomes_tempo_run(self, healthy_ctx):
        rule = StandardizeWorkoutName()
        # quality 인데 Interval step 없고 Run 만 있는 경우 → 'Tempo Run'
        from .conftest import make_step

        tempo_steps = [
            make_step("Warmup", 600, "6:45"),
            make_step("Run", 1500, "5:15"),
            make_step("Cooldown", 300, "7:10"),
        ]
        days = [make_day(healthy_ctx.today + timedelta(days=i), "base") for i in range(7)]
        days[1] = make_day(
            healthy_ctx.today + timedelta(days=1),
            "quality",
            workout_name="Custom Tempo",
            steps=tempo_steps,
        )
        plan = TrainingPlan(plan=days)
        violations = rule.check(plan, healthy_ctx)
        assert any(v.day_index == 1 for v in violations)
        fixed = rule.correct(plan, healthy_ctx, violations)
        assert fixed.plan[1].workout.workout_name == "Tempo Run"

    def test_long_run_gets_long_run_name(self, healthy_ctx):
        rule = StandardizeWorkoutName()
        days = [make_day(healthy_ctx.today + timedelta(days=i), "base") for i in range(7)]
        days[0] = make_day(healthy_ctx.today, "long_run", workout_name="토요 롱 런")
        plan = TrainingPlan(plan=days)
        violations = rule.check(plan, healthy_ctx)
        fixed = rule.correct(plan, healthy_ctx, violations)
        assert fixed.plan[0].workout.workout_name == "Long Run"
