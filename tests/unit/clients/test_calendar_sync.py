from datetime import date

from running_coach.clients.google_calendar.sync import CalendarSyncService


class _EventsApi:
    def __init__(self):
        self.inserted = []
        self.deleted = []

    def list(self, **_kwargs):
        return self

    def insert(self, **kwargs):
        self.inserted.append(kwargs)
        return self

    def delete(self, **kwargs):
        self.deleted.append(kwargs)
        return self

    def execute(self):
        return {"items": []}


class _CalendarsApi:
    def __init__(self):
        self.inserted = []

    def insert(self, body):
        self.inserted.append(body)
        return self

    def execute(self):
        return {"id": "calendar-1"}


class _CalendarListApi:
    def list(self):
        return self

    def execute(self):
        return {"items": []}


class _FakeService:
    def __init__(self):
        self._events = _EventsApi()
        self._calendars = _CalendarsApi()
        self._calendar_list = _CalendarListApi()

    def events(self):
        return self._events

    def calendars(self):
        return self._calendars

    def calendarList(self):  # noqa: N802
        return self._calendar_list


def test_sync_completed_activities_creates_workout_events():
    service = _FakeService()
    sync = CalendarSyncService(service)

    sync.sync_completed_activities(
        activities=[
            {
                "garminActivityId": 123,
                "activityDate": "2026-04-17",
                "startedAt": "2026-04-17T06:00:00+09:00",
                "title": "러닝",
                "sportType": "러닝",
                "distanceKm": 5.11,
                "durationSeconds": 1711,
                "avgPace": "5:35",
                "avgHr": 148,
                "maxHr": 162,
                "elevationGainM": 22,
                "executionStatus": "completed_unplanned",
                "notes": "Garmin 실제 수행 기록",
            }
        ],
        as_of=date(2026, 4, 18),
    )

    assert len(service._events.inserted) == 1
    event = service._events.inserted[0]["body"]
    assert event["summary"] == "러닝 5.11km"
    assert event["extendedProperties"]["private"]["source"] == "running_coach_activity"
    assert event["start"]["dateTime"] == "2026-04-17T06:00:00+09:00"
    assert "상태: 비계획 수행" in event["description"]


def test_sync_completed_activities_includes_plan_comparison_lines():
    service = _FakeService()
    sync = CalendarSyncService(service)

    sync.sync_completed_activities(
        activities=[
            {
                "garminActivityId": 123,
                "activityDate": "2026-04-17",
                "startedAt": "2026-04-17T06:00:00+09:00",
                "title": "러닝",
                "sportType": "러닝",
                "distanceKm": 5.11,
                "durationSeconds": 1711,
                "avgPace": "5:35",
                "avgHr": 148,
                "maxHr": 162,
                "elevationGainM": 22,
                "plannedWorkoutName": "Running Coach: Recovery Run",
                "plannedCategory": "recovery",
                "actualCategory": "base",
                "executionStatus": "completed_substituted",
                "targetMatchScore": 0.72,
                "notes": "Garmin 실제 수행 기록",
            }
        ],
        as_of=date(2026, 4, 18),
    )

    description = service._events.inserted[0]["body"]["description"]
    assert "계획 워크아웃: Running Coach: Recovery Run" in description
    assert "계획 유형: recovery" in description
    assert "실제 유형: base" in description
    assert "매칭 점수: 72점" in description
    assert "상태: 대체 수행" in description
