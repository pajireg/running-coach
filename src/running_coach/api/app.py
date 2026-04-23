"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from ..application import CoachingApplicationService, UserApplicationService
from ..config.settings import Settings, get_settings
from ..storage import AdminSettingsService, DatabaseClient, UserService
from .admin import create_admin_router
from .users import create_user_router


def create_app(settings: Settings | None = None) -> FastAPI:
    """HTTP API 앱 생성."""
    active_settings = settings or get_settings()
    db = DatabaseClient(active_settings.database_url)
    admin_settings = AdminSettingsService(
        db=db,
        deployment_defaults=active_settings.deployment_llm_settings(),
    )
    coaching_app = CoachingApplicationService(settings=active_settings)
    user_app = UserApplicationService(
        user_service=UserService(db=db),
        admin_settings=admin_settings,
        settings=active_settings,
        coaching_service=coaching_app,
    )

    app = FastAPI(title="Running Coach API")
    app.include_router(
        create_admin_router(
            admin_settings=admin_settings,
            admin_api_key=active_settings.admin_api_key,
        )
    )
    app.include_router(create_user_router(user_app))
    return app
