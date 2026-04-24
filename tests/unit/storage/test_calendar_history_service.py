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
                    "provider": "garmin",
                    "provider_activity_id": "123",
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
                    "execution_quality": "회복 세션치고 강도가 높았음",
                }
            ]
        return []


def test_list_recent_completed_activities_returns_calendar_payload():
    service = _CalendarHistoryService(_FakeDb(), "user@example.com")

    activities = service.list_recent_completed_activities(as_of=date(2026, 4, 18), days=30)

    assert len(activities) == 1
    assert activities[0]["provider"] == "garmin"
    assert activities[0]["providerActivityId"] == "123"
    assert activities[0]["sportType"] == "러닝"
    assert activities[0]["distanceKm"] == 5.11
    assert activities[0]["executionStatus"] == "completed_substituted"
    assert "상태: 대체 수행" in activities[0]["notes"]
    assert "수행 품질: 회복 세션치고 강도가 높았음" in activities[0]["notes"]


class _UnplannedCalendarHistoryService(CoachingHistoryService):
    def _athlete_id(self) -> str:  # type: ignore[override]
        return "athlete-1"

    def _fetchall(self, query: str, params: dict[str, object]):  # type: ignore[override]
        if "FROM activities" in query:
            return [
                {
                    "provider": "garmin",
                    "provider_activity_id": "456",
                    "activity_date": date(2026, 4, 16),
                    "started_at": datetime(2026, 4, 16, 6, 0, tzinfo=timezone.utc),
                    "name": "인터벌 러닝",
                    "sport_type": "running",
                    "distance_km": 8.0,
                    "duration_seconds": 2400,
                    "avg_pace": "5:00",
                    "avg_hr": 170,
                    "max_hr": 184,
                    "elevation_gain_m": 10,
                    "execution_status": "completed_unplanned",
                    "planned_category": "unplanned",
                    "actual_category": "quality",
                    "planned_workout_name": None,
                    "target_match_score": None,
                    "execution_quality": "의도한 강도 자극이 잘 들어간 품질 세션",
                    "deviation_reason": "unplanned_session",
                    "coach_interpretation": (
                        "계획에 없던 세션으로, 다음 주 부하 해석 시 " "별도로 반영해야 합니다."
                    ),
                }
            ]
        return []


def test_list_recent_completed_activities_describes_unplanned_hard_session():
    service = _UnplannedCalendarHistoryService(_FakeDb(), "user@example.com")

    activities = service.list_recent_completed_activities(as_of=date(2026, 4, 18), days=30)

    assert len(activities) == 1
    assert "비계획 고강도 러닝" in activities[0]["notes"]
    assert "계획 밖 고강도 세션" in activities[0]["notes"]
    assert "수행 품질: 의도한 강도 자극이 잘 들어간 품질 세션" in activities[0]["notes"]
