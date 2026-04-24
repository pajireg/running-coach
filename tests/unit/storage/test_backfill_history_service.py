from datetime import date

from running_coach.storage.history_service import CoachingHistoryService


class _FakeDb:
    pass


class _RecordingHistoryService(CoachingHistoryService):
    def __init__(self):
        super().__init__(_FakeDb(), "user@example.com")
        self.executed = []

    def _athlete_id(self) -> str:  # type: ignore[override]
        return "athlete-1"

    def _execute(self, query: str, params: dict[str, object]) -> None:  # type: ignore[override]
        self.executed.append((query, params))


def test_backfill_planned_workouts_inserts_calendar_history():
    service = _RecordingHistoryService()

    inserted = service.backfill_planned_workouts(
        [
            {
                "date": "2026-04-10",
                "title": "Running Coach: Base Run",
                "elapsedDuration": 1800,
                "workoutId": 123,
            }
        ]
    )

    assert inserted == 1
    _, params = service.executed[0]
    assert params["workout_date"] == date(2026, 4, 10)
    assert params["delivery_provider"] == "garmin"
    assert params["delivery_status"] == "scheduled_backfill"


def test_is_running_sport_type_filters_non_running():
    assert CoachingHistoryService._is_running_sport_type({"activityType": {"typeKey": "running"}})
    assert not CoachingHistoryService._is_running_sport_type(
        {"activityType": {"typeKey": "cycling"}}
    )
