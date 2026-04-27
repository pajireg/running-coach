"""User-scoped runtime factory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..clients.google_calendar import GoogleCalendarClient
from ..config.settings import Settings
from ..models.user import UserContext
from ..storage import IntegrationCredentialService
from .container import ServiceContainer


@dataclass(frozen=True)
class ProviderRuntimeCredentials:
    """Credentials needed to construct the current training-data provider client."""

    email: str
    password: str
    source: str


class UserRuntimeFactory:
    """Build user-scoped runtime containers from per-user integration credentials."""

    def __init__(
        self,
        settings: Settings,
        integration_credentials: IntegrationCredentialService,
    ):
        self.settings = settings
        self.integration_credentials = integration_credentials

    def create_container(self, user_context: UserContext) -> ServiceContainer:
        provider_credentials = self._resolve_training_provider_credentials(user_context)
        calendar_client = self._resolve_google_calendar_client(user_context)
        return ServiceContainer.create_for_user(
            settings=self.settings,
            user_context=user_context,
            provider_email=provider_credentials.email,
            provider_password=provider_credentials.password,
            calendar_client=calendar_client,
        )

    def _resolve_training_provider_credentials(
        self, user_context: UserContext
    ) -> ProviderRuntimeCredentials:
        record = self.integration_credentials.get_credential(user_context.user_id, "garmin")
        if record is None:
            raise ValueError("Training-data provider integration is not configured for this user")
        if record.status != "active":
            raise ValueError(
                f"Training-data provider integration is not active: {record.status}"
            )

        payload = self.integration_credentials.decrypt_payload(record)
        email = str(payload.get("email") or record.external_account_id or "").strip()
        password = str(payload.get("password") or "").strip()
        if not email:
            raise ValueError("Training-data provider credential payload is missing email")
        if not password:
            raise ValueError("Training-data provider credential payload is missing password")
        return ProviderRuntimeCredentials(email=email, password=password, source="db")

    def _resolve_google_calendar_client(self, user_context: UserContext) -> GoogleCalendarClient:
        record = self.integration_credentials.get_credential(
            user_context.user_id,
            "google_calendar",
        )
        if record is None or record.status != "active":
            return GoogleCalendarClient(enabled=False)

        payload = self.integration_credentials.decrypt_payload(record)
        token_info = self._google_calendar_token_info_from_payload(payload)
        return GoogleCalendarClient(token_info=token_info)

    def _google_calendar_token_info_from_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        nested = payload.get("authorized_user_info")
        if isinstance(nested, dict):
            return nested
        return payload
