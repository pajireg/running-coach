from datetime import date, timedelta

import pytest

from running_coach.models.training import TrainingPlan, WorkoutStep


def _day_payload(day_date: date, workout_name: str = "Running Coach: Easy"):
    return {
        "date": day_date.isoformat(),
        "workout": {
            "workoutName": workout_name,
            "description": "설명",
            "sportType": "RUNNING",
            "steps": [
                {
                    "type": "Run",
                    "durationValue": 1800,
                    "durationUnit": "second",
                    "targetType": "speed",
                    "targetValue": "5:00",
                }
            ],
        },
    }


def test_workout_step_normalizes_pace_suffix():
    step = WorkoutStep.model_validate(
        {
            "type": "Run",
            "durationValue": 600,
            "durationUnit": "second",
            "targetType": "speed",
            "targetValue": "4:45/km",
        }
    )

    assert step.target_value == "4:45"


def test_training_plan_requires_consecutive_dates():
    start = date(2026, 4, 17)
    payload = {"plan": [_day_payload(start + timedelta(days=i)) for i in range(7)]}
    TrainingPlan.model_validate(payload)

    payload["plan"][3]["date"] = (start + timedelta(days=5)).isoformat()
    with pytest.raises(ValueError, match="consecutive"):
        TrainingPlan.model_validate(payload)
