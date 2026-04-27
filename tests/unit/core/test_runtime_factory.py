"""User runtime factory tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from running_coach.core.runtime_factory import UserRuntimeFactory
from running_coach.models.llm_settings import LLMSettings
from running_coach.models.user import UserContext
from running_coach.storage.integration_credentials import IntegrationCredentialRecord


def _context() -> UserContext:
    return UserContext(
        user_id="user-1",
        external_key="runner-1",
        llm_settings=LLMSettings(
            planner_mode="legacy",
            llm_provider="gemini",
            llm_model="gemini-2.5-flash",
        ),
    )


class FakeIntegrationCredentials:
    def __init__(self, record=None, payload=None, records=None, payloads=None):
        self.record = record
        self.payload = payload or {}
        self.records = records or {}
        self.payloads = payloads or {}

    def get_credential(self, user_id, provider):
        assert user_id == "user-1"
        if provider in self.records:
            return self.records[provider]
        if provider != "garmin":
            return None
        return self.record

    def decrypt_payload(self, record):
        for provider, provider_record in self.records.items():
            if record is provider_record:
                return self.payloads.get(provider, {})
        assert record is self.record
        return self.payload


def test_runtime_factory_uses_db_credentials(monkeypatch):
    created = {}

    def fake_create_for_user(**kwargs):
        created.update(kwargs)
        return "container"

    monkeypatch.setattr(
        "running_coach.core.runtime_factory.ServiceContainer.create_for_user",
        fake_create_for_user,
    )
    record = IntegrationCredentialRecord(
        user_id="user-1",
        provider="garmin",
        encrypted_payload="encrypted",
        status="active",
        external_account_id="runner@example.com",
    )
    factory = UserRuntimeFactory(
        settings=SimpleNamespace(),  # type: ignore[arg-type]
        integration_credentials=FakeIntegrationCredentials(
            record=record,
            payload={"email": "runner@example.com", "password": "db-password"},
        ),  # type: ignore[arg-type]
    )

    factory.create_container(_context())

    assert created["provider_email"] == "runner@example.com"
    assert created["provider_password"] == "db-password"


def test_runtime_factory_falls_back_to_external_account_id_when_payload_missing_email(
    monkeypatch,
):
    created = {}

    def fake_create_for_user(**kwargs):
        created.update(kwargs)
        return "container"

    monkeypatch.setattr(
        "running_coach.core.runtime_factory.ServiceContainer.create_for_user",
        fake_create_for_user,
    )
    record = IntegrationCredentialRecord(
        user_id="user-1",
        provider="garmin",
        encrypted_payload="encrypted",
        status="active",
        external_account_id="runner@example.com",
    )
    factory = UserRuntimeFactory(
        settings=SimpleNamespace(),  # type: ignore[arg-type]
        integration_credentials=FakeIntegrationCredentials(
            record=record,
            payload={"password": "db-password"},
        ),  # type: ignore[arg-type]
    )

    factory.create_container(_context())

    assert created["provider_email"] == "runner@example.com"
    assert created["provider_password"] == "db-password"


def test_runtime_factory_rejects_missing_credentials():
    factory = UserRuntimeFactory(
        settings=SimpleNamespace(),  # type: ignore[arg-type]
        integration_credentials=FakeIntegrationCredentials(),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="not configured"):
        factory.create_container(_context())


def test_runtime_factory_rejects_inactive_credentials():
    record = IntegrationCredentialRecord(
        user_id="user-1",
        provider="garmin",
        encrypted_payload="encrypted",
        status="reauth_required",
    )
    factory = UserRuntimeFactory(
        settings=SimpleNamespace(),  # type: ignore[arg-type]
        integration_credentials=FakeIntegrationCredentials(record=record),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="not active"):
        factory.create_container(_context())


def test_runtime_factory_uses_db_google_calendar_token_for_active_user(monkeypatch):
    created = {}

    def fake_create_for_user(**kwargs):
        created.update(kwargs)
        return "container"

    monkeypatch.setattr(
        "running_coach.core.runtime_factory.ServiceContainer.create_for_user",
        fake_create_for_user,
    )
    garmin_record = IntegrationCredentialRecord(
        user_id="user-1",
        provider="garmin",
        encrypted_payload="garmin",
        status="active",
    )
    calendar_record = IntegrationCredentialRecord(
        user_id="user-1",
        provider="google_calendar",
        encrypted_payload="calendar",
        status="active",
    )
    factory = UserRuntimeFactory(
        settings=SimpleNamespace(),  # type: ignore[arg-type]
        integration_credentials=FakeIntegrationCredentials(
            records={
                "garmin": garmin_record,
                "google_calendar": calendar_record,
            },
            payloads={
                "garmin": {"email": "runner@example.com", "password": "db-password"},
                "google_calendar": {
                    "authorized_user_info": {
                        "token": "access-token",
                        "refresh_token": "refresh-token",
                        "client_id": "client-id",
                        "client_secret": "client-secret",
                    }
                },
            },
        ),  # type: ignore[arg-type]
    )

    factory.create_container(_context())

    calendar_client = created["calendar_client"]
    assert calendar_client.enabled is True
    assert calendar_client.token_info["token"] == "access-token"


def test_runtime_factory_disables_google_calendar_when_no_token(monkeypatch):
    created = {}

    def fake_create_for_user(**kwargs):
        created.update(kwargs)
        return "container"

    monkeypatch.setattr(
        "running_coach.core.runtime_factory.ServiceContainer.create_for_user",
        fake_create_for_user,
    )
    garmin_record = IntegrationCredentialRecord(
        user_id="user-1",
        provider="garmin",
        encrypted_payload="garmin",
        status="active",
    )
    factory = UserRuntimeFactory(
        settings=SimpleNamespace(),  # type: ignore[arg-type]
        integration_credentials=FakeIntegrationCredentials(
            records={"garmin": garmin_record},
            payloads={"garmin": {"email": "runner@example.com", "password": "db-password"}},
        ),  # type: ignore[arg-type]
    )

    factory.create_container(_context())

    assert created["calendar_client"].enabled is False
