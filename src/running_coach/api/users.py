"""User-facing API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status

from ..application import UserApplicationService
from ..models.user import (
    RunSyncRequest,
    UserContext,
    UserCreateRequest,
    UserCreateResponse,
    UserPreferencesPatch,
)


def create_user_router(user_app: UserApplicationService) -> APIRouter:
    """Create user-facing API router."""
    router = APIRouter(prefix="/v1", tags=["users"])

    def require_current_user(
        authorization: str | None = Header(default=None),
    ) -> UserContext:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing API key",
            )
        api_key = authorization[7:].strip()
        current_user = user_app.authenticate_api_key(api_key)
        if current_user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )
        return current_user

    @router.post("/users", response_model=UserCreateResponse, status_code=status.HTTP_201_CREATED)
    async def create_user(payload: UserCreateRequest) -> UserCreateResponse:
        return user_app.create_user(payload)

    @router.get("/me")
    async def get_me(
        current_user: UserContext = Depends(require_current_user),
    ) -> dict[str, object]:
        return user_app.get_user_profile(current_user.user_id).model_dump(by_alias=True)

    @router.patch("/me/preferences")
    async def patch_me_preferences(
        patch: UserPreferencesPatch,
        current_user: UserContext = Depends(require_current_user),
    ) -> dict[str, object]:
        return user_app.update_user_preferences(current_user.user_id, patch).model_dump(
            by_alias=True
        )

    @router.post("/runs/sync")
    async def sync_runs(
        payload: RunSyncRequest,
        current_user: UserContext = Depends(require_current_user),
    ) -> dict[str, str]:
        try:
            return user_app.run_user_sync(
                user_id=current_user.user_id,
                run_mode=payload.mode,
            ).model_dump()
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc

    return router
