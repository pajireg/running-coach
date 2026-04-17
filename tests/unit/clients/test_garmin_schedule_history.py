from datetime import date

from running_coach.clients.garmin.client import GarminClient


class _FakeConnection:
    def get_scheduled_workouts(self, year, month):
        if (year, month) == (2026, 4):
            return {
                "calendarItems": [
                    {
                        "id": 1,
                        "date": "2026-04-10",
                        "itemType": "workout",
                        "title": "Running Coach: Base Run",
                        "elapsedDuration": 1800,
                        "workoutId": 123,
                    },
                    {
                        "id": 3,
                        "date": "2026-04-09",
                        "itemType": "workout",
                        "title": "Coach Gemini: Recovery Run",
                        "elapsedDuration": 1500,
                        "workoutId": 456,
                    },
                    {
                        "id": 2,
                        "date": "2026-04-11",
                        "itemType": "activity",
                        "title": "Morning Run",
                    },
                ]
            }
        return {"calendarItems": []}


def test_get_recent_scheduled_workout_history_filters_supported_generated_workouts():
    client = GarminClient.__new__(GarminClient)
    client._connection = _FakeConnection()

    items = client.get_recent_scheduled_workout_history(target_date=date(2026, 4, 18), days=14)

    assert len(items) == 2
    assert items[0]["title"] == "Coach Gemini: Recovery Run"
    assert items[1]["title"] == "Running Coach: Base Run"
