"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from ..config.settings import Settings, get_settings
from ..storage import AdminSettingsService, DatabaseClient
from .admin import create_admin_router


def create_app(settings: Settings | None = None) -> FastAPI:
    """HTTP API 앱 생성."""
    active_settings = settings or get_settings()
    db = DatabaseClient(active_settings.database_url)
    admin_settings = AdminSettingsService(
        db=db,
        deployment_defaults=active_settings.deployment_llm_settings(),
    )

    app = FastAPI(title="Running Coach Admin")
    app.include_router(
        create_admin_router(
            admin_settings=admin_settings,
            admin_api_key=active_settings.admin_api_key,
        )
    )
    return app
