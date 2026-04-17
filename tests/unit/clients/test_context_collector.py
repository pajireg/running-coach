from datetime import date

from running_coach.clients.garmin.context_collector import ContextDataCollector


class _FakeGarmin:
    def __init__(self, calendar_items, activities):
        self.calendar_items = calendar_items
        self.activities = activities

    def get_activities_by_date(self, *_args, **_kwargs):
        return [
            {
                "activityName": "Easy Run",
                "activityType": {"typeKey": "running"},
                "distance": 10000,
                "duration": 3600,
                "calories": 700,
            }
        ]

    def get_activities(self, *_args, **_kwargs):
        return self.activities

    def get_scheduled_workouts(self, *_args, **_kwargs):
        return {"calendarItems": self.calendar_items}


def test_collect_converts_distances_and_preserves_schedule_details():
    target_date = date(2026, 4, 17)
    yesterday = date(2026, 4, 16)
    six_days_ago = date(2026, 4, 11)

    collector = ContextDataCollector(
        _FakeGarmin(
            calendar_items=[
                {
                    "id": 1,
                    "date": yesterday.isoformat(),
                    "itemType": "workout",
                    "title": "Running Coach: Tempo",
                },
                {
                    "id": 2,
                    "date": six_days_ago.isoformat(),
                    "itemType": "activity",
                    "title": "Morning Run",
                    "distance": 12000,
                    "elapsedDuration": 3600,
                    "averageHR": 150,
                },
            ],
            activities=[
                {
                    "activityId": 100,
                    "activityName": "Morning Run",
                    "startTimeLocal": six_days_ago.strftime("%Y-%m-%d 06:00:00"),
                    "activityType": {"typeKey": "running"},
                    "distance": 12000,
                    "duration": 3600,
                    "calories": 500,
                },
                {
                    "activityId": 101,
                    "activityName": "Bike Ride",
                    "startTimeLocal": yesterday.strftime("%Y-%m-%d 18:00:00"),
                    "activityType": {"typeKey": "cycling"},
                    "distance": 30000,
                    "duration": 5400,
                    "calories": 700,
                }
            ],
        )
    )

    context = collector.collect(target_date)

    assert context.yesterday_actual[0].distance == 10.0
    assert context.yesterday_planned[0].title == "Running Coach: Tempo"
    activity_item = next(item for item in context.current_schedule if item.type == "activity")
    assert activity_item.details == "(12.0km, 1h 0m 0s, HR: 150)"
    assert context.recent_7d_run_distance_km == 12.0
    assert context.recent_30d_run_count == 1
    assert context.recent_7d_non_running_duration_minutes == 90
    assert context.recent_7d_non_running_sessions == 1
    assert context.recent_7d_non_running_types == ["cycling"]
    assert any("12.0km" in item for item in context.to_dict()["current_schedule"])
