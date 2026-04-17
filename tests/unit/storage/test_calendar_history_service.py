from datetime import date, datetime, timezone

from running_coach.storage.history_service import CoachingHistoryService


class _FakeDb:
    pass


class _CalendarHistoryService(CoachingHistoryService):
    def _athlete_id(self) -> str:  # type: ignore[override]
        return "athlete-1"

    def _fetchall(self, query: str, params: dict[str, object]):  # type: ignore[override]
        if "FROM activities" in query:
            return [
                {
                    "garmin_activity_id": 123,
                    "activity_date": date(2026, 4, 17),
                    "started_at": datetime(2026, 4, 17, 6, 0, tzinfo=timezone.utc),
                    "name": "러닝",
                    "sport_type": "running",
                    "distance_km": 5.11,
                    "duration_seconds": 1711,
                    "avg_pace": "5:35",
                    "avg_hr": 148,
                    "max_hr": 162,
                    "elevation_gain_m": 22,
                    "execution_status": "completed_substituted",
                    "planned_category": "recovery",
                    "actual_category": "base",
                    "planned_workout_name": "Running Coach: Recovery Run",
                    "target_match_score": 0.72,
                }
            ]
        return []


def test_list_recent_completed_activities_returns_calendar_payload():
    service = _CalendarHistoryService(_FakeDb(), "user@example.com")

    activities = service.list_recent_completed_activities(as_of=date(2026, 4, 18), days=30)

    assert len(activities) == 1
    assert activities[0]["garminActivityId"] == 123
    assert activities[0]["sportType"] == "러닝"
    assert activities[0]["distanceKm"] == 5.11
    assert activities[0]["executionStatus"] == "completed_substituted"
    assert "상태: 대체 수행" in activities[0]["notes"]
