from datetime import date

from running_coach.clients.garmin.workout_manager import WorkoutManager
from running_coach.models.training import Workout


class _FakeGarmin:
    def __init__(self):
        self.uploaded_payload = None
        self.scheduled = None
        self.deleted_ids = []

    def upload_workout(self, payload):
        self.uploaded_payload = payload
        return {"workoutId": 42}

    def schedule_workout(self, workout_id, date_str):
        self.scheduled = (workout_id, date_str)

    def get_workouts(self):
        return [{"workoutName": "Running Coach: Easy", "workoutId": 10}]

    def delete_workout(self, workout_id):
        self.deleted_ids.append(workout_id)


def test_create_workout_uses_json_upload_payload():
    garmin = _FakeGarmin()
    manager = WorkoutManager(garmin)
    workout = Workout.model_validate(
        {
            "workoutName": "Intervals",
            "description": "테스트",
            "sportType": "RUNNING",
            "steps": [
                {
                    "type": "Warmup",
                    "durationValue": 600,
                    "durationUnit": "second",
                    "targetType": "no_target",
                    "targetValue": "0:00",
                },
                {
                    "type": "Interval",
                    "durationValue": 300,
                    "durationUnit": "second",
                    "targetType": "speed",
                    "targetValue": "4:30",
                },
            ],
        }
    )

    workout_id = manager.create_workout(workout)

    assert workout_id == "42"
    assert garmin.uploaded_payload["workoutName"] == "Intervals"
    assert garmin.uploaded_payload["estimatedDurationInSecs"] == 900
    assert garmin.uploaded_payload["sportType"]["displayOrder"] == 1
    step = garmin.uploaded_payload["workoutSegments"][0]["workoutSteps"][1]
    assert step["type"] == "ExecutableStepDTO"
    assert step["stepType"]["stepTypeId"] == 3
    assert step["targetType"]["workoutTargetTypeKey"] == "pace.zone"
    assert step["targetValueOne"] is not None
    assert step["targetValueTwo"] is not None
    assert step["targetValueOne"] > step["targetValueTwo"]


def test_schedule_and_cleanup_use_native_methods_when_available():
    garmin = _FakeGarmin()
    manager = WorkoutManager(garmin)

    manager.schedule_workout("42", date(2026, 4, 17))
    deleted_count = manager.delete_generated_workouts()

    assert garmin.scheduled == ("42", "2026-04-17")
    assert deleted_count == 1
    assert garmin.deleted_ids == [10]


def test_cleanup_prefers_database_workout_ids():
    garmin = _FakeGarmin()
    manager = WorkoutManager(garmin)

    deleted_count = manager.delete_generated_workouts(workout_ids=["100", "101"])

    assert deleted_count == 2
    assert garmin.deleted_ids == ["100", "101"]


def test_warmup_and_cooldown_use_wider_pace_margins():
    garmin = _FakeGarmin()
    manager = WorkoutManager(garmin)
    workout = Workout.model_validate(
        {
            "workoutName": "Base Run",
            "description": "테스트",
            "sportType": "RUNNING",
            "steps": [
                {
                    "type": "Warmup",
                    "durationValue": 600,
                    "durationUnit": "second",
                    "targetType": "speed",
                    "targetValue": "6:45",
                },
                {
                    "type": "Run",
                    "durationValue": 1800,
                    "durationUnit": "second",
                    "targetType": "speed",
                    "targetValue": "6:00",
                },
                {
                    "type": "Cooldown",
                    "durationValue": 300,
                    "durationUnit": "second",
                    "targetType": "speed",
                    "targetValue": "7:10",
                },
            ],
        }
    )

    manager.create_workout(workout)

    steps = garmin.uploaded_payload["workoutSegments"][0]["workoutSteps"]
    warmup_range = steps[0]["targetValueOne"] - steps[0]["targetValueTwo"]
    run_range = steps[1]["targetValueOne"] - steps[1]["targetValueTwo"]
    cooldown_range = steps[2]["targetValueOne"] - steps[2]["targetValueTwo"]
    assert warmup_range > run_range
    assert cooldown_range > warmup_range
