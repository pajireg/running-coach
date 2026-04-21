"""Safety rule 테스트 공용 픽스처."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from running_coach.coaching.context import (
    AvailabilitySlot,
    CoachingContext,
    CoachingScores,
)
from running_coach.core.pace_zones import PaceZones
from running_coach.models.training import (
    DailyPlan,
    TrainingPlan,
    Workout,
    WorkoutStep,
)

DEFAULT_ZONES = PaceZones(
    interval="4:30",
    threshold="5:00",
    tempo="5:15",
    base="6:45",
    long_run="6:40",
    recovery="7:20",
    warmup="7:00",   # base(6:45)보다 15s 느림 — Pfitzinger 기준
    cooldown="7:20", # recovery pace — 가장 편안한 속도
)


def make_step(
    step_type: str = "Run",
    seconds: int = 1800,
    pace: str = "6:45",
) -> WorkoutStep:
    return WorkoutStep(
        type=step_type,
        duration_value=seconds,
        duration_unit="second",
        target_type="speed",
        target_value=pace,
    )


def make_workout(
    name: str = "Base Run",
    steps: list[WorkoutStep] | None = None,
) -> Workout:
    if steps is None:
        if "Rest" in name:
            return Workout(workout_name=name, steps=[])
        steps = [make_step("Run", 1800, "6:45")]
    return Workout(workout_name=name, steps=steps)


def make_day(
    d: date,
    session_type: str = "base",
    workout_name: str | None = None,
    steps: list[WorkoutStep] | None = None,
    planned_minutes: int | None = None,
) -> DailyPlan:
    default_names = {
        "rest": "Rest Day",
        "recovery": "Recovery Run",
        "base": "Base Run",
        "quality": "Interval",  # StandardizeWorkoutName 기대값
        "long_run": "Long Run",
    }
    name = workout_name or default_names[session_type]
    if session_type == "rest":
        steps = []
    elif steps is None:
        if session_type == "quality":
            steps = [
                make_step("Warmup", 900, "7:00"),
                make_step("Interval", 240, "4:30"),
                make_step("Recovery", 120, "7:20"),
                make_step("Interval", 240, "4:30"),
                make_step("Recovery", 120, "7:20"),
                make_step("Cooldown", 600, "7:20"),
            ]
        elif session_type == "long_run":
            steps = [
                make_step("Warmup", 600, "7:00"),
                make_step("Run", 3600, "6:40"),
                make_step("Cooldown", 300, "7:20"),
            ]
        elif session_type == "recovery":
            steps = [
                make_step("Warmup", 300, "7:20"),
                make_step("Run", 1500, "7:20"),
                make_step("Cooldown", 300, "7:20"),
            ]
        else:
            steps = [
                make_step("Warmup", 600, "7:00"),
                make_step("Run", 1800, "6:45"),
                make_step("Cooldown", 300, "7:20"),
            ]
    return DailyPlan(
        date=d,
        session_type=session_type,
        planned_minutes=planned_minutes,
        workout=make_workout(name, steps),
    )


def make_plan(session_types: list[str], start: date | None = None) -> TrainingPlan:
    """7일 계획 생성; session_types 길이 7 이어야 함."""
    start = start or date(2026, 4, 20)  # Monday
    days = [make_day(start + timedelta(days=i), st) for i, st in enumerate(session_types)]
    return TrainingPlan(plan=days)


@pytest.fixture
def zones() -> PaceZones:
    return DEFAULT_ZONES


@pytest.fixture
def healthy_ctx(zones) -> CoachingContext:
    """부상 없음, availability 전부 가용, chronic load 50km."""
    return CoachingContext(
        today=date(2026, 4, 20),
        scores=CoachingScores(
            readiness=70,
            fatigue=40,
            injury_risk=20,
            active_injury_severity=0,
            chronic_ewma_load=50.0,
        ),
        pace_zones=zones,
        availability={i: AvailabilitySlot(weekday=i, is_available=True) for i in range(7)},
    )


@pytest.fixture
def injured_ctx(zones) -> CoachingContext:
    """활성 부상 severity=6."""
    return CoachingContext(
        today=date(2026, 4, 20),
        scores=CoachingScores(
            readiness=50,
            fatigue=60,
            injury_risk=70,
            active_injury_severity=6,
            chronic_ewma_load=40.0,
        ),
        pace_zones=zones,
        availability={i: AvailabilitySlot(weekday=i, is_available=True) for i in range(7)},
    )


@pytest.fixture
def mildly_injured_ctx(zones) -> CoachingContext:
    """활성 부상 severity=4."""
    return CoachingContext(
        today=date(2026, 4, 20),
        scores=CoachingScores(
            readiness=55,
            fatigue=50,
            injury_risk=55,
            active_injury_severity=4,
            chronic_ewma_load=40.0,
        ),
        pace_zones=zones,
        availability={i: AvailabilitySlot(weekday=i, is_available=True) for i in range(7)},
    )
