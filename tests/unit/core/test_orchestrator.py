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
        self.cleanup_ids = None

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

    def cleanup_existing_workouts(self, workout_ids=None):
        self.cleanup_ids = workout_ids
        return 0


class _FakeGeminiClient:
    def __init__(self):
        self.call_count = 0
        self.last_create_kwargs = None

    def create_training_plan(self, **_kwargs):
        self.call_count += 1
        self.last_create_kwargs = _kwargs
        return TrainingPlan.model_validate(
            {
                "plan": [
                    {
                        "date": "2026-04-17",
                        "workout": {
                            "workoutName": "Base Run",
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
                            "workoutName": "Base Run",
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
                            "workoutName": "Rest Day",
                            "description": "휴식",
                            "sportType": "RUNNING",
                            "steps": [],
                        },
                    },
                    {
                        "date": "2026-04-20",
                        "workout": {
                            "workoutName": "Base Run",
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
                            "workoutName": "Base Run",
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
                            "workoutName": "Base Run",
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
                            "workoutName": "Base Run",
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
        self.cleared = []
        self.freshness = {
            "hasActivePlan": False,
            "hasNewActivitySinceLastPlan": False,
            "lastPlanCreatedAt": None,
            "latestActivityCreatedAt": None,
            "shouldGeneratePlan": True,
            "reasons": ["missing_active_plan"],
        }

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

    def list_planned_external_workout_ids(self, **_kwargs):
        return ["old-1"]

    def clear_delivery_results(self, **kwargs):
        self.cleared.append(kwargs)

    def record_coach_decision(self, **_kwargs):
        return None

    def record_delivery_result(self, **kwargs):
        self.synced.append(kwargs)

    def summarize_plan_freshness(self, **_kwargs):
        return self.freshness


class _FakeHistoryWriteService:
    def __init__(self, history_service):
        self.db = history_service.db
        self._history = history_service

    def ensure_athlete(self, **kwargs):
        return self._history.ensure_athlete(**kwargs)

    def record_daily_metrics(self, metrics):
        return self._history.record_daily_metrics(metrics)

    def record_training_plan(self, plan):
        return self._history.record_training_plan(plan)

    def record_coach_decision(self, **kwargs):
        return self._history.record_coach_decision(**kwargs)

    def record_activities(self, activities):
        return self._history.record_activities(activities)


class _FakeHistoryReadService:
    def __init__(self, history_service):
        self._history = history_service

    def summarize_training_background(self, as_of):
        return {}

    def list_planned_external_workout_ids(self, **kwargs):
        return self._history.list_planned_external_workout_ids(**kwargs)

    def summarize_plan_freshness(self, **kwargs):
        return self._history.summarize_plan_freshness(**kwargs)

    def fetch_future_plan(self, from_date, days=6):
        return []

    def list_recent_completed_activities(self, **kwargs):
        return []


class _FakeHistorySyncService:
    def __init__(self, history_service):
        self._history = history_service

    def rebuild_recent_workout_executions(self, **kwargs):
        return self._history.rebuild_recent_workout_executions(**kwargs)

    def backfill_planned_workouts(self, scheduled_items):
        return self._history.backfill_planned_workouts(scheduled_items)

    def clear_delivery_results(self, **kwargs):
        return self._history.clear_delivery_results(**kwargs)

    def record_delivery_result(self, **kwargs):
        return self._history.record_delivery_result(**kwargs)


class _FakeCalendarClient:
    def authenticate(self):
        return None

    sync_service = SimpleNamespace(sync=lambda _plan: None)


def test_run_once_persists_provider_delivery_results():
    history_service = _FakeHistoryService()
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
        history_service=history_service,
        history_write_service=_FakeHistoryWriteService(history_service),
        history_read_service=_FakeHistoryReadService(history_service),
        history_sync_service=_FakeHistorySyncService(history_service),
    )

    orchestrator = TrainingOrchestrator(container)

    result = orchestrator.run_once()

    assert result is True
    assert container.garmin_client.cleanup_ids == ["old-1"]
    assert container.history_service.cleared[0]["start_date"].isoformat() == "2026-04-17"
    assert len(container.history_service.synced) == 6
    assert container.history_service.synced[0]["delivery_provider"] == "garmin"
    assert container.history_service.synced[0]["external_workout_id"] == "id-1"
    assert container.history_service.synced[0]["delivery_status"] == "scheduled"


def test_run_once_prefers_provider_neutral_training_data_dependency():
    history_service = _FakeHistoryService()
    training_data_provider = _FakeGarminClient()
    container = SimpleNamespace(
        settings=SimpleNamespace(
            race=SimpleNamespace(has_goal=False),
            persist_history=True,
            include_strength=False,
            garmin_email="user@example.com",
            max_heart_rate=None,
        ),
        garmin_client=SimpleNamespace(),
        training_data_provider=training_data_provider,
        workout_delivery_provider=training_data_provider.workout_manager,
        gemini_client=_FakeGeminiClient(),
        calendar_client=_FakeCalendarClient(),
        history_service=history_service,
        history_write_service=_FakeHistoryWriteService(history_service),
        history_read_service=_FakeHistoryReadService(history_service),
        history_sync_service=_FakeHistorySyncService(history_service),
    )

    result = TrainingOrchestrator(container).run_once()

    assert result is True
    assert training_data_provider.cleanup_ids == ["old-1"]
    assert training_data_provider.workout_manager.created


def test_auto_mode_skips_llm_when_plan_is_fresh():
    history_service = _FakeHistoryService()
    history_service.freshness = {
        "hasActivePlan": True,
        "hasNewActivitySinceLastPlan": False,
        "lastPlanCreatedAt": "2026-04-18T17:00:00+09:00",
        "latestActivityCreatedAt": "2026-04-18T08:00:00+09:00",
        "shouldGeneratePlan": False,
        "reasons": [],
    }
    gemini_client = _FakeGeminiClient()
    garmin_client = _FakeGarminClient()
    container = SimpleNamespace(
        settings=SimpleNamespace(
            race=SimpleNamespace(has_goal=False),
            persist_history=True,
            include_strength=False,
            garmin_email="user@example.com",
            max_heart_rate=None,
        ),
        garmin_client=garmin_client,
        gemini_client=gemini_client,
        calendar_client=_FakeCalendarClient(),
        history_service=history_service,
        history_write_service=_FakeHistoryWriteService(history_service),
        history_read_service=_FakeHistoryReadService(history_service),
        history_sync_service=_FakeHistorySyncService(history_service),
    )

    result = TrainingOrchestrator(container).run_once(run_mode="auto")

    assert result is True
    assert gemini_client.call_count == 0
    assert garmin_client.cleanup_ids is None
    assert garmin_client.workout_manager.created == []


def test_run_once_uses_user_context_include_strength():
    gemini_client = _FakeGeminiClient()
    history_service = _FakeHistoryService()
    container = SimpleNamespace(
        settings=SimpleNamespace(
            race=SimpleNamespace(has_goal=False),
            persist_history=True,
            include_strength=False,
            garmin_email="user@example.com",
            max_heart_rate=None,
        ),
        garmin_client=_FakeGarminClient(),
        gemini_client=gemini_client,
        calendar_client=_FakeCalendarClient(),
        history_service=history_service,
        history_write_service=_FakeHistoryWriteService(history_service),
        history_read_service=_FakeHistoryReadService(history_service),
        history_sync_service=_FakeHistorySyncService(history_service),
        user_context=None,
    )

    result = TrainingOrchestrator(container).run_once(
        user_context=SimpleNamespace(
            user_id="user-1",
            external_key="runner-1",
            include_strength=True,
            garmin_email="user@example.com",
        )
    )

    assert result is True
    assert gemini_client.last_create_kwargs["include_strength"] is True
