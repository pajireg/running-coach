"""Shared runtime composition for CLI and HTTP surfaces."""

from __future__ import annotations

from dataclasses import dataclass

from ..application import CoachingApplicationService, UserApplicationService
from ..config.settings import Settings
from ..storage import (
    AdminSettingsService,
    CredentialCipher,
    DatabaseClient,
    IntegrationCredentialService,
    UserCoachingStateService,
    UserService,
)
from ..storage.schema import ensure_core_schema


@dataclass
class ApplicationRuntime:
    """Shared application runtime dependencies."""

    settings: Settings
    db: DatabaseClient
    admin_settings: AdminSettingsService
    integration_credentials: IntegrationCredentialService
    coaching_app: CoachingApplicationService
    user_app: UserApplicationService


def create_application_runtime(settings: Settings) -> ApplicationRuntime:
    """Compose the shared application runtime once per process."""
    db = DatabaseClient(settings.database_url)
    ensure_core_schema(db)
    credential_cipher = (
        CredentialCipher(settings.app_encryption_key) if settings.app_encryption_key else None
    )
    integration_credentials = IntegrationCredentialService(
        db=db,
        cipher=credential_cipher,
    )
    admin_settings = AdminSettingsService(
        db=db,
        deployment_defaults=settings.deployment_llm_settings(),
    )
    coaching_app = CoachingApplicationService(
        settings=settings,
        user_state_service=UserCoachingStateService(db=db),
    )
    user_app = UserApplicationService(
        user_service=UserService(db=db),
        admin_settings=admin_settings,
        integration_credentials=integration_credentials,
        settings=settings,
        coaching_service=coaching_app,
    )
    return ApplicationRuntime(
        settings=settings,
        db=db,
        admin_settings=admin_settings,
        integration_credentials=integration_credentials,
        coaching_app=coaching_app,
        user_app=user_app,
    )
