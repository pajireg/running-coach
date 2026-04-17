from types import SimpleNamespace

from running_coach.core.orchestrator import TrainingOrchestrator
from running_coach.models.training import TrainingPlan


class _FakeWorkoutManager:
    def __init__(self):
        self.created = []
        self.scheduled = []

    def create_workout(self, workout):
        workout_id = f"id-{len(self.created) + 1}"
        self.created.append(workout.workout_name)
        return workout_id

    def schedule_workout(self, workout_id, target_date):
        self.scheduled.append((workout_id, target_date.isoformat()))
        return {"scheduledWorkoutId": workout_id}


class _FakeGarminClient:
    def __init__(self):
        self.workout_manager = _FakeWorkoutManager()

    def login(self):
        return None

    def get_advanced_metrics(self):
        return SimpleNamespace(
            date="2026-04-17",
            health=SimpleNamespace(to_dict=lambda: {}),
            performance=SimpleNamespace(
                training_load=SimpleNamespace(status="MAINTAINING", to_dict=lambda: {})
            ),
            context=SimpleNamespace(to_dict=lambda: {}),
        )

    def get_recent_activity_history(self):
        return []

    def get_recent_scheduled_workout_history(self, target_date=None):
        return []

    def cleanup_existing_workouts(self):
        return 0


class _FakeGeminiClient:
    def create_training_plan(self, **_kwargs):
        return TrainingPlan.model_validate(
            {
                "plan": [
                    {
                        "date": "2026-04-17",
                        "workout": {
                            "workoutName": "Running Coach: Base Run",
                            "description": "테스트",
                            "sportType": "RUNNING",
                            "steps": [
                                {
                                    "type": "Warmup",
                                    "durationValue": 600,
                                    "durationUnit": "second",
                                    "targetType": "no_target",
                                    "targetValue": "0:00",
                                }
                            ],
                        },
                    },
                    {
                        "date": "2026-04-18",
                        "workout": {
                            "workoutName": "Running Coach: Base Run",
                            "description": "테스트",
                            "sportType": "RUNNING",
                            "steps": [
                                {
                                    "type": "Run",
                                    "durationValue": 1200,
                                    "durationUnit": "second",
                                    "targetType": "no_target",
                                    "targetValue": "0:00",
                                }
                            ],
                        },
                    },
                    {
                        "date": "2026-04-19",
                        "workout": {
                            "workoutName": "Running Coach: Rest Day",
                            "description": "휴식",
                            "sportType": "RUNNING",
                            "steps": [],
                        },
                    },
                    {
                        "date": "2026-04-20",
                        "workout": {
                            "workoutName": "Running Coach: Base Run",
                            "description": "테스트",
                            "sportType": "RUNNING",
                            "steps": [
                                {
                                    "type": "Run",
                                    "durationValue": 1200,
                                    "durationUnit": "second",
                                    "targetType": "no_target",
                                    "targetValue": "0:00",
                                }
                            ],
                        },
                    },
                    {
                        "date": "2026-04-21",
                        "workout": {
                            "workoutName": "Running Coach: Base Run",
                            "description": "테스트",
                            "sportType": "RUNNING",
                            "steps": [
                                {
                                    "type": "Run",
                                    "durationValue": 1200,
                                    "durationUnit": "second",
                                    "targetType": "no_target",
                                    "targetValue": "0:00",
                                }
                            ],
                        },
                    },
                    {
                        "date": "2026-04-22",
                        "workout": {
                            "workoutName": "Running Coach: Base Run",
                            "description": "테스트",
                            "sportType": "RUNNING",
                            "steps": [
                                {
                                    "type": "Run",
                                    "durationValue": 1200,
                                    "durationUnit": "second",
                                    "targetType": "no_target",
                                    "targetValue": "0:00",
                                }
                            ],
                        },
                    },
                    {
                        "date": "2026-04-23",
                        "workout": {
                            "workoutName": "Running Coach: Base Run",
                            "description": "테스트",
                            "sportType": "RUNNING",
                            "steps": [
                                {
                                    "type": "Run",
                                    "durationValue": 1200,
                                    "durationUnit": "second",
                                    "targetType": "no_target",
                                    "targetValue": "0:00",
                                }
                            ],
                        },
                    },
                ]
            }
        )


class _FakeHistoryService:
    def __init__(self):
        self.db = SimpleNamespace(ping=lambda: None)
        self.synced = []

    def ensure_athlete(self, **_kwargs):
        return None

    def record_daily_metrics(self, _metrics):
        return None

    def record_activities(self, _activities):
        return None

    def backfill_planned_workouts(self, _items):
        return 0

    def rebuild_recent_workout_executions(self, _as_of):
        return 0

    def record_training_plan(self, _plan):
        return None

    def record_coach_decision(self, **_kwargs):
        return None

    def record_garmin_sync_result(self, **kwargs):
        self.synced.append(kwargs)


class _FakeCalendarClient:
    def authenticate(self):
        return None

    sync_service = SimpleNamespace(sync=lambda _plan: None)


def test_run_once_persists_garmin_sync_results():
    container = SimpleNamespace(
        settings=SimpleNamespace(
            race=SimpleNamespace(has_goal=False),
            persist_history=True,
            include_strength=False,
            garmin_email="user@example.com",
            max_heart_rate=None,
        ),
        garmin_client=_FakeGarminClient(),
        gemini_client=_FakeGeminiClient(),
        calendar_client=_FakeCalendarClient(),
        history_service=_FakeHistoryService(),
    )

    orchestrator = TrainingOrchestrator(container)

    result = orchestrator.run_once()

    assert result is True
    assert len(container.history_service.synced) == 6
    assert container.history_service.synced[0]["garmin_workout_id"] == "id-1"
    assert container.history_service.synced[0]["garmin_schedule_status"] == "scheduled"
