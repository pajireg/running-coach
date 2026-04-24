"""User-scoped runtime factory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config.settings import Settings
from ..models.user import UserContext
from ..storage import IntegrationCredentialService
from .container import ServiceContainer


@dataclass(frozen=True)
class GarminRuntimeCredentials:
    """Credentials needed to construct the current Garmin client."""

    email: str
    password: str
    source: str


class UserRuntimeFactory:
    """Build user-scoped runtime containers from deployment config and user state."""

    def __init__(
        self,
        settings: Settings,
        integration_credentials: IntegrationCredentialService,
    ):
        self.settings = settings
        self.integration_credentials = integration_credentials

    def create_container(self, user_context: UserContext) -> ServiceContainer:
        garmin_credentials = self._resolve_garmin_credentials(user_context)
        return ServiceContainer.create_for_user(
            settings=self.settings,
            user_context=user_context,
            garmin_email=garmin_credentials.email,
            garmin_password=garmin_credentials.password,
        )

    def _resolve_garmin_credentials(self, user_context: UserContext) -> GarminRuntimeCredentials:
        if not user_context.garmin_email:
            raise ValueError("Garmin integration is not configured for this user")

        if user_context.garmin_email == self.settings.garmin_email:
            return GarminRuntimeCredentials(
                email=self.settings.garmin_email,
                password=self.settings.garmin_password,
                source="env_compat",
            )

        record = self.integration_credentials.get_credential(user_context.user_id, "garmin")
        if record is None:
            raise ValueError("Garmin integration is not configured for this user")
        if record.status != "active":
            raise ValueError(f"Garmin integration is not active: {record.status}")

        payload = self.integration_credentials.decrypt_payload(record)
        return self._garmin_credentials_from_payload(payload, user_context)

    def _garmin_credentials_from_payload(
        self,
        payload: dict[str, Any],
        user_context: UserContext,
    ) -> GarminRuntimeCredentials:
        email = str(payload.get("email") or user_context.garmin_email or "").strip()
        password = str(payload.get("password") or "").strip()
        if not email:
            raise ValueError("Garmin credential payload is missing email")
        if not password:
            raise ValueError("Garmin credential payload is missing password")
        return GarminRuntimeCredentials(
            email=email,
            password=password,
            source="db",
        )
