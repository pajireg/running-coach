"""FastAPI application factory tests."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from running_coach.api import app as app_module
from running_coach.config.settings import Settings


def _settings(cors_origins: str = "*") -> Settings:
    return Settings(
        garmin_email="runner@example.com",
        garmin_password="secret-password",
        gemini_api_key="gemini-key",
        api_cors_allow_origins=cors_origins,
    )


def test_health_endpoint_returns_ok(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "create_application_runtime",
        lambda settings: SimpleNamespace(admin_settings=object(), user_app=object()),
    )
    client = TestClient(app_module.create_app(_settings()))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_app_allows_configured_cors_origin(monkeypatch):
    monkeypatch.setattr(
        app_module,
        "create_application_runtime",
        lambda settings: SimpleNamespace(admin_settings=object(), user_app=object()),
    )
    client = TestClient(app_module.create_app(_settings("https://app.example.com")))

    response = client.options(
        "/v1/me",
        headers={
            "Origin": "https://app.example.com",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://app.example.com"
