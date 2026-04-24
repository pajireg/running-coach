"""User-facing API tests."""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from running_coach.api.users import create_user_router
from running_coach.models.llm_settings import LLMSettings
from running_coach.models.user import (
    DashboardActivity,
    DashboardPlannedWorkout,
    IntegrationConnection,
    IntegrationStatus,
    RunSyncResponse,
    UserContext,
    UserCreateRequest,
    UserCreateResponse,
    UserDashboard,
    UserIntegrationsResponse,
    UserPreferences,
    UserPreferencesPatch,
    UserProfile,
)


class FakeUserApplicationService:
    def __init__(self):
        self.profile = UserProfile(
            userId="user-1",
            externalKey="runner-1",
            displayName="Runner One",
            garminEmail="runner@example.com",
            preferences=UserPreferences(
                timezone="Asia/Seoul",
                locale="ko",
                scheduleTimes="05:00,17:00",
                runMode="auto",
                includeStrength=False,
            ),
            llmSettings=LLMSettings(
                planner_mode="legacy",
                llm_provider="gemini",
                llm_model="gemini-2.5-flash",
            ),
            integrationStatus=IntegrationStatus(
                garmin="configured",
                googleCalendar="env_compat",
            ),
        )
        self.dashboard = UserDashboard(
            user=self.profile,
            schedule={
                "nextRunAt": datetime(2026, 4, 24, 20, 0, tzinfo=timezone.utc),
                "lastStatus": "completed",
                "failureCount": 0,
            },
            currentPlan=[
                DashboardPlannedWorkout(
                    date=date(2026, 4, 25),
                    workoutName="Base Run",
                    sessionType="base",
                    workoutType="Base Run",
                    plannedMinutes=45,
                    isRest=False,
                )
            ],
            recentActivities=[
                DashboardActivity(
                    provider="garmin",
                    providerActivityId="activity-1",
                    activityDate=date(2026, 4, 24),
                    title="Morning Run",
                    sportType="Running",
                    distanceKm=8.1,
                    durationSeconds=2700,
                )
            ],
        )
        self.integrations = UserIntegrationsResponse(
            integrations=[
                IntegrationConnection(
                    provider="garmin",
                    displayName="Garmin Connect",
                    status="configured",
                    connected=True,
                    source="profile",
                    capabilities=["training_data", "workout_delivery"],
                ),
                IntegrationConnection(
                    provider="healthkit",
                    displayName="Apple HealthKit",
                    status="coming_soon",
                    connected=False,
                    source="planned",
                    capabilities=["health_data", "activity_data"],
                ),
            ]
        )
        self.current_user = UserContext(
            user_id="user-1",
            external_key="runner-1",
            display_name="Runner One",
            garmin_email="runner@example.com",
            timezone="Asia/Seoul",
            locale="ko",
            schedule_times="05:00,17:00",
            run_mode="auto",
            include_strength=False,
            llm_settings=self.profile.llm_settings,
        )

    def create_user(self, payload: UserCreateRequest) -> UserCreateResponse:
        self.profile.display_name = payload.display_name
        self.profile.garmin_email = payload.garmin_email
        self.profile.preferences.timezone = payload.timezone
        self.profile.preferences.locale = payload.locale
        self.profile.preferences.schedule_times = payload.schedule_times
        self.profile.preferences.run_mode = payload.run_mode
        self.profile.preferences.include_strength = payload.include_strength
        return UserCreateResponse(apiKey="rcu_test", user=self.profile)

    def authenticate_api_key(self, api_key: str) -> UserContext | None:
        if api_key != "rcu_test":
            return None
        return self.current_user

    def get_user_profile(self, user_id: str) -> UserProfile:
        assert user_id == "user-1"
        return self.profile

    def get_dashboard(self, user_id: str) -> UserDashboard:
        assert user_id == "user-1"
        return self.dashboard

    def get_integrations(self, user_id: str) -> UserIntegrationsResponse:
        assert user_id == "user-1"
        return self.integrations

    def update_user_preferences(self, user_id: str, patch: UserPreferencesPatch) -> UserProfile:
        assert user_id == "user-1"
        if patch.display_name is not None:
            self.profile.display_name = patch.display_name
        if patch.locale is not None:
            self.profile.preferences.locale = patch.locale
        if patch.include_strength is not None:
            self.profile.preferences.include_strength = patch.include_strength
        if patch.run_mode is not None:
            self.profile.preferences.run_mode = patch.run_mode
        return self.profile

    def run_user_sync(self, user_id: str, run_mode: str = "auto") -> RunSyncResponse:
        assert user_id == "user-1"
        return RunSyncResponse(status="completed", mode=run_mode)

    def record_feedback(self, user_id: str, feedback) -> None:
        assert user_id == "user-1"
        assert feedback.feedback_date == date(2026, 4, 24)

    def update_availability(self, user_id: str, **kwargs) -> None:
        assert user_id == "user-1"
        assert kwargs["weekday"] == 2
        assert kwargs["is_available"] is True

    def upsert_race_goal(self, user_id: str, **kwargs) -> None:
        assert user_id == "user-1"
        assert kwargs["goal_name"] == "10K PB"

    def upsert_training_block(self, user_id: str, **kwargs) -> None:
        assert user_id == "user-1"
        assert kwargs["phase"] == "build"

    def upsert_injury_status(self, user_id: str, **kwargs) -> None:
        assert user_id == "user-1"
        assert kwargs["injury_area"] == "calf"


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(create_user_router(FakeUserApplicationService()))  # type: ignore[arg-type]
    return TestClient(app)


def test_create_user_returns_one_time_api_key():
    client = _client()

    response = client.post(
        "/v1/users",
        json={
            "displayName": "Runner One",
            "garminEmail": "runner@example.com",
            "timezone": "Asia/Seoul",
            "locale": "ko",
            "scheduleTimes": "05:00,17:00",
            "runMode": "plan",
            "includeStrength": True,
        },
    )

    assert response.status_code == 201
    assert response.json()["apiKey"] == "rcu_test"
    assert response.json()["user"]["preferences"]["runMode"] == "plan"
    assert response.json()["user"]["preferences"]["includeStrength"] is True


def test_get_me_requires_api_key():
    client = _client()

    response = client.get("/v1/me")

    assert response.status_code == 401


def test_get_me_returns_current_user_profile():
    client = _client()

    response = client.get("/v1/me", headers={"Authorization": "Bearer rcu_test"})

    assert response.status_code == 200
    assert response.json()["userId"] == "user-1"
    assert response.json()["llmSettings"]["llmModel"] == "gemini-2.5-flash"


def test_get_me_dashboard_returns_app_home_summary():
    client = _client()

    response = client.get("/v1/me/dashboard", headers={"Authorization": "Bearer rcu_test"})

    assert response.status_code == 200
    assert response.json()["user"]["userId"] == "user-1"
    assert response.json()["schedule"]["nextRunAt"] == "2026-04-24T20:00:00Z"
    assert response.json()["currentPlan"][0]["workoutName"] == "Base Run"
    assert response.json()["recentActivities"][0]["provider"] == "garmin"


def test_get_me_integrations_returns_provider_inventory():
    client = _client()

    response = client.get("/v1/me/integrations", headers={"Authorization": "Bearer rcu_test"})

    assert response.status_code == 200
    assert response.json()["integrations"][0]["provider"] == "garmin"
    assert response.json()["integrations"][0]["connected"] is True
    assert response.json()["integrations"][1]["provider"] == "healthkit"
    assert response.json()["integrations"][1]["status"] == "coming_soon"


def test_patch_me_preferences_updates_profile():
    client = _client()

    response = client.patch(
        "/v1/me/preferences",
        headers={"Authorization": "Bearer rcu_test"},
        json={"displayName": "Updated Runner", "includeStrength": True, "runMode": "plan"},
    )

    assert response.status_code == 200
    assert response.json()["displayName"] == "Updated Runner"
    assert response.json()["preferences"]["runMode"] == "plan"
    assert response.json()["preferences"]["includeStrength"] is True


def test_sync_runs_uses_current_user():
    client = _client()

    response = client.post(
        "/v1/runs/sync",
        headers={"Authorization": "Bearer rcu_test"},
        json={"mode": "auto"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "completed", "mode": "auto"}


def test_feedback_endpoint_uses_current_user():
    client = _client()

    response = client.post(
        "/v1/me/feedback",
        headers={"Authorization": "Bearer rcu_test"},
        json={"feedbackDate": "2026-04-24", "fatigueScore": 6},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_availability_endpoint_uses_current_user():
    client = _client()

    response = client.post(
        "/v1/me/availability",
        headers={"Authorization": "Bearer rcu_test"},
        json={"weekday": 2, "isAvailable": True, "maxDurationMinutes": 45},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
