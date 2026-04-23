"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from ..config.settings import Settings, get_settings
from ..core.bootstrap import create_application_runtime
from .admin import create_admin_router
from .users import create_user_router


def create_app(settings: Settings | None = None) -> FastAPI:
    """HTTP API 앱 생성."""
    active_settings = settings or get_settings()
    runtime = create_application_runtime(active_settings)

    app = FastAPI(title="Running Coach API")
    app.include_router(
        create_admin_router(
            admin_settings=runtime.admin_settings,
            admin_api_key=active_settings.admin_api_key,
        )
    )
    app.include_router(create_user_router(runtime.user_app))
    return app
