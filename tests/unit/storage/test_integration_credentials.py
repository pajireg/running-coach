"""Integration credential storage tests."""

from __future__ import annotations

import pytest

from running_coach.storage.integration_credentials import (
    CredentialCipher,
    IntegrationCredentialService,
)


class FakeIntegrationCredentialService(IntegrationCredentialService):
    def __init__(self, cipher=None):
        super().__init__(db=object(), cipher=cipher)  # type: ignore[arg-type]
        self.rows: dict[tuple[str, str], dict[str, object]] = {}

    def _execute(self, query: str, params: dict[str, object]) -> None:  # type: ignore[override]
        key = (str(params["user_id"]), str(params["provider"]))
        existing = self.rows.get(key, {})
        encrypted_payload = str(params.get("encrypted_payload") or "")
        self.rows[key] = {
            "user_id": key[0],
            "provider": key[1],
            "encrypted_payload": encrypted_payload or existing.get("encrypted_payload", ""),
            "status": params["status"],
            "last_error": params.get("last_error"),
        }

    def _fetchall(self, query: str, params: dict[str, object]):  # type: ignore[override]
        user_id = str(params["user_id"])
        if "SELECT provider, status" in query:
            return [
                {"provider": row["provider"], "status": row["status"]}
                for row in self.rows.values()
                if row["user_id"] == user_id
            ]
        if "ORDER BY provider" in query:
            return [row for row in self.rows.values() if row["user_id"] == user_id]
        provider = str(params["provider"])
        row = self.rows.get((user_id, provider))
        return [row] if row else []


def test_credential_cipher_round_trips_json_payload():
    cipher = CredentialCipher("test-secret")

    token = cipher.encrypt_json({"accessToken": "abc", "refreshToken": "def"})
    payload = cipher.decrypt_json(token)

    assert payload == {"accessToken": "abc", "refreshToken": "def"}
    assert "abc" not in token


def test_credential_cipher_rejects_tampered_payload():
    cipher = CredentialCipher("test-secret")
    token = cipher.encrypt_json({"accessToken": "abc"})
    tampered = token[:-3] + "abc"

    with pytest.raises(ValueError):
        cipher.decrypt_json(tampered)


def test_integration_credentials_store_status_without_cipher():
    service = FakeIntegrationCredentialService()

    service.set_status(
        "user-1",
        "garmin",
        "reauth_required",
        last_error="expired",
    )

    assert service.get_statuses("user-1") == {"garmin": "reauth_required"}
    record = service.get_credential("user-1", "garmin")
    assert record is not None
    assert record.last_error == "expired"
    records = service.list_credentials("user-1")
    assert records[0].provider == "garmin"
    assert records[0].last_error == "expired"


def test_integration_credentials_encrypt_and_decrypt_payload():
    service = FakeIntegrationCredentialService(cipher=CredentialCipher("test-secret"))

    record = service.upsert_payload(
        "user-1",
        "google_calendar",
        {"token": "secret-token"},
    )

    assert record.status == "active"
    assert "secret-token" not in record.encrypted_payload
    assert service.decrypt_payload(record) == {"token": "secret-token"}
