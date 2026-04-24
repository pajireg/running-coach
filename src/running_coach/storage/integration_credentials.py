"""User-scoped integration credential and status storage."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from typing import Any, Literal, Optional, cast

from .database import DatabaseClient

IntegrationProvider = Literal[
    "garmin",
    "google_calendar",
    "healthkit",
    "health_connect",
    "google_fit",
]
IntegrationStatusValue = Literal["active", "reauth_required", "disabled", "error"]


@dataclass(frozen=True)
class IntegrationCredentialRecord:
    """Storage projection for one provider credential row."""

    user_id: str
    provider: IntegrationProvider
    encrypted_payload: str
    status: IntegrationStatusValue
    last_error: str | None = None


class CredentialCipher:
    """Small local envelope cipher used until a KMS/Fernet backend is introduced."""

    def __init__(self, secret: str):
        if not secret:
            raise ValueError("APP_ENCRYPTION_KEY must not be empty")
        self._key = hashlib.sha256(secret.encode("utf-8")).digest()

    def encrypt_json(self, payload: dict[str, Any]) -> str:
        plaintext = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        nonce = os.urandom(16)
        ciphertext = self._xor(plaintext, nonce)
        tag = hmac.new(self._key, nonce + ciphertext, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(nonce + tag + ciphertext).decode("ascii")

    def decrypt_json(self, token: str) -> dict[str, Any]:
        raw = base64.urlsafe_b64decode(token.encode("ascii"))
        nonce, tag, ciphertext = raw[:16], raw[16:48], raw[48:]
        expected = hmac.new(self._key, nonce + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise ValueError("Encrypted integration payload failed integrity check")
        plaintext = self._xor(ciphertext, nonce)
        return cast(dict[str, Any], json.loads(plaintext.decode("utf-8")))

    def _xor(self, data: bytes, nonce: bytes) -> bytes:
        output = bytearray()
        counter = 0
        while len(output) < len(data):
            block = hashlib.sha256(self._key + nonce + counter.to_bytes(4, "big")).digest()
            output.extend(block)
            counter += 1
        return bytes(value ^ mask for value, mask in zip(data, output))


class IntegrationCredentialService:
    """Persistence service for user-owned provider credentials and status."""

    def __init__(self, db: DatabaseClient, cipher: CredentialCipher | None = None):
        self.db = db
        self.cipher = cipher

    def get_statuses(self, user_id: str) -> dict[IntegrationProvider, IntegrationStatusValue]:
        rows = self._fetchall(
            """
            SELECT provider, status
            FROM user_integration_credentials
            WHERE athlete_id = %(user_id)s
            """,
            {"user_id": user_id},
        )
        return {
            cast(IntegrationProvider, row["provider"]): cast(IntegrationStatusValue, row["status"])
            for row in rows
        }

    def get_credential(
        self,
        user_id: str,
        provider: IntegrationProvider,
    ) -> IntegrationCredentialRecord | None:
        row = self._fetchone(
            """
            SELECT athlete_id AS user_id, provider, encrypted_payload, status, last_error
            FROM user_integration_credentials
            WHERE athlete_id = %(user_id)s
              AND provider = %(provider)s
            """,
            {"user_id": user_id, "provider": provider},
        )
        if row is None:
            return None
        return IntegrationCredentialRecord(
            user_id=str(row["user_id"]),
            provider=cast(IntegrationProvider, row["provider"]),
            encrypted_payload=str(row.get("encrypted_payload") or ""),
            status=cast(IntegrationStatusValue, row["status"]),
            last_error=row.get("last_error"),
        )

    def upsert_payload(
        self,
        user_id: str,
        provider: IntegrationProvider,
        payload: dict[str, Any],
        *,
        status: IntegrationStatusValue = "active",
    ) -> IntegrationCredentialRecord:
        if self.cipher is None:
            raise ValueError("APP_ENCRYPTION_KEY is required to store integration credentials")
        encrypted_payload = self.cipher.encrypt_json(payload)
        self._upsert(
            user_id=user_id,
            provider=provider,
            encrypted_payload=encrypted_payload,
            status=status,
            last_error=None,
        )
        record = self.get_credential(user_id, provider)
        if record is None:
            raise ValueError(f"Failed to upsert integration credential: {provider}")
        return record

    def decrypt_payload(self, record: IntegrationCredentialRecord) -> dict[str, Any]:
        if self.cipher is None:
            raise ValueError("APP_ENCRYPTION_KEY is required to read integration credentials")
        return self.cipher.decrypt_json(record.encrypted_payload)

    def set_status(
        self,
        user_id: str,
        provider: IntegrationProvider,
        status: IntegrationStatusValue,
        *,
        last_error: str | None = None,
    ) -> None:
        self._upsert(
            user_id=user_id,
            provider=provider,
            encrypted_payload="",
            status=status,
            last_error=last_error,
        )

    def _upsert(
        self,
        *,
        user_id: str,
        provider: IntegrationProvider,
        encrypted_payload: str,
        status: IntegrationStatusValue,
        last_error: str | None,
    ) -> None:
        self._execute(
            """
            INSERT INTO user_integration_credentials (
                athlete_id,
                provider,
                encrypted_payload,
                status,
                last_error,
                updated_at
            )
            VALUES (
                %(user_id)s,
                %(provider)s,
                %(encrypted_payload)s,
                %(status)s,
                %(last_error)s,
                NOW()
            )
            ON CONFLICT (athlete_id, provider)
            DO UPDATE SET
                encrypted_payload = COALESCE(
                    NULLIF(EXCLUDED.encrypted_payload, ''),
                    user_integration_credentials.encrypted_payload
                ),
                status = EXCLUDED.status,
                last_error = EXCLUDED.last_error,
                updated_at = NOW()
            """,
            {
                "user_id": user_id,
                "provider": provider,
                "encrypted_payload": encrypted_payload,
                "status": status,
                "last_error": last_error,
            },
        )

    def _execute(self, query: str, params: dict[str, Any]) -> None:
        with self.db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)

    def _fetchall(self, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        with self.db.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()
                return cast(list[dict[str, Any]], list(rows))

    def _fetchone(self, query: str, params: dict[str, Any]) -> Optional[dict[str, Any]]:
        rows = self._fetchall(query, params)
        return rows[0] if rows else None
