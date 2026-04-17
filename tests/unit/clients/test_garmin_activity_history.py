from running_coach.clients.garmin.client import GarminClient


class _FakeGarminConnection:
    def get_activities(self, *_args, **_kwargs):
        return [
            {
                "activityId": 101,
                "startTimeLocal": "2026-04-16T06:00:00",
                "activityName": "Morning Run",
            }
        ]

    def get_activity_details(self, activity_id):
        assert activity_id == 101
        return {"summaryDTO": {"distance": 10000, "duration": 3600, "averageHR": 150}}

    def get_activity_splits(self, activity_id):
        assert activity_id == 101
        return {"lapDTOs": [{"distance": 1000, "duration": 300, "averageHR": 145}]}


def test_get_recent_activity_history_collects_detail_and_splits():
    client = GarminClient(email="user@example.com", password="pw", settings=None)  # type: ignore[arg-type]
    client._connection = _FakeGarminConnection()  # type: ignore[assignment]

    history = client.get_recent_activity_history(days=1000)

    assert len(history) == 1
    assert history[0]["summary"]["activityId"] == 101
    assert history[0]["details"]["summaryDTO"]["distance"] == 10000
    assert history[0]["splits"][0]["duration"] == 300
