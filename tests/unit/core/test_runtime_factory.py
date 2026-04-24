"""User runtime factory tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from running_coach.core.runtime_factory import UserRuntimeFactory
from running_coach.models.llm_settings import LLMSettings
from running_coach.models.user import UserContext
from running_coach.storage.integration_credentials import IntegrationCredentialRecord


def _context(garmin_email: str = "runner@example.com") -> UserContext:
    return UserContext(
        user_id="user-1",
        external_key="runner-1",
        garmin_email=garmin_email,
        llm_settings=LLMSettings(
            planner_mode="legacy",
            llm_provider="gemini",
            llm_model="gemini-2.5-flash",
        ),
    )


class FakeIntegrationCredentials:
    def __init__(self, record=None, payload=None):
        self.record = record
        self.payload = payload or {}

    def get_credential(self, user_id, provider):
        assert user_id == "user-1"
        assert provider == "garmin"
        return self.record

    def decrypt_payload(self, record):
        assert record is self.record
        return self.payload


def test_runtime_factory_uses_env_credentials_for_compat_user(monkeypatch):
    created = {}

    def fake_create_for_user(**kwargs):
        created.update(kwargs)
        return "container"

    monkeypatch.setattr(
        "running_coach.core.runtime_factory.ServiceContainer.create_for_user",
        fake_create_for_user,
    )
    settings = SimpleNamespace(
        garmin_email="runner@example.com",
        garmin_password="env-password",
    )
    factory = UserRuntimeFactory(
        settings=settings,  # type: ignore[arg-type]
        integration_credentials=FakeIntegrationCredentials(),  # type: ignore[arg-type]
    )

    container = factory.create_container(_context("runner@example.com"))

    assert container == "container"
    assert created["garmin_email"] == "runner@example.com"
    assert created["garmin_password"] == "env-password"


def test_runtime_factory_uses_db_credentials_for_non_env_user(monkeypatch):
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
    )
    factory = UserRuntimeFactory(
        settings=SimpleNamespace(
            garmin_email="env@example.com",
            garmin_password="env-password",
        ),  # type: ignore[arg-type]
        integration_credentials=FakeIntegrationCredentials(
            record=record,
            payload={"email": "runner@example.com", "password": "db-password"},
        ),  # type: ignore[arg-type]
    )

    factory.create_container(_context("runner@example.com"))

    assert created["garmin_email"] == "runner@example.com"
    assert created["garmin_password"] == "db-password"


def test_runtime_factory_rejects_inactive_garmin_credentials():
    record = IntegrationCredentialRecord(
        user_id="user-1",
        provider="garmin",
        encrypted_payload="encrypted",
        status="reauth_required",
    )
    factory = UserRuntimeFactory(
        settings=SimpleNamespace(
            garmin_email="env@example.com",
            garmin_password="env-password",
        ),  # type: ignore[arg-type]
        integration_credentials=FakeIntegrationCredentials(record=record),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="not active"):
        factory.create_container(_context("runner@example.com"))
