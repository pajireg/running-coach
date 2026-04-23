"""User-facing API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status

from ..application import UserApplicationService
from ..models.feedback import SubjectiveFeedback
from ..models.user import (
    RunSyncRequest,
    UserContext,
    UserCreateRequest,
    UserCreateResponse,
    UserPreferencesPatch,
)
from ..models.user_coaching import (
    AvailabilityRuleRequest,
    InjuryStatusRequest,
    MutationResponse,
    RaceGoalRequest,
    TrainingBlockRequest,
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

    @router.post("/me/feedback", response_model=MutationResponse)
    async def record_feedback(
        payload: SubjectiveFeedback,
        current_user: UserContext = Depends(require_current_user),
    ) -> MutationResponse:
        user_app.record_feedback(current_user.user_id, payload)
        return MutationResponse()

    @router.post("/me/availability", response_model=MutationResponse)
    async def update_availability(
        payload: AvailabilityRuleRequest,
        current_user: UserContext = Depends(require_current_user),
    ) -> MutationResponse:
        user_app.update_availability(
            current_user.user_id,
            weekday=payload.weekday,
            is_available=payload.is_available,
            max_duration_minutes=payload.max_duration_minutes,
            preferred_session_type=payload.preferred_session_type,
        )
        return MutationResponse()

    @router.post("/me/goals", response_model=MutationResponse)
    async def upsert_goal(
        payload: RaceGoalRequest,
        current_user: UserContext = Depends(require_current_user),
    ) -> MutationResponse:
        user_app.upsert_race_goal(
            current_user.user_id,
            goal_name=payload.goal_name,
            race_date=payload.race_date,
            distance=payload.distance,
            goal_time=payload.goal_time,
            target_pace=payload.target_pace,
            priority=payload.priority,
            is_active=payload.is_active,
        )
        return MutationResponse()

    @router.post("/me/blocks", response_model=MutationResponse)
    async def upsert_block(
        payload: TrainingBlockRequest,
        current_user: UserContext = Depends(require_current_user),
    ) -> MutationResponse:
        user_app.upsert_training_block(
            current_user.user_id,
            phase=payload.phase,
            starts_on=payload.starts_on,
            ends_on=payload.ends_on,
            focus=payload.focus,
            weekly_volume_target_km=payload.weekly_volume_target_km,
        )
        return MutationResponse()

    @router.post("/me/injuries", response_model=MutationResponse)
    async def upsert_injury(
        payload: InjuryStatusRequest,
        current_user: UserContext = Depends(require_current_user),
    ) -> MutationResponse:
        user_app.upsert_injury_status(
            current_user.user_id,
            status_date=payload.status_date,
            injury_area=payload.injury_area,
            severity=payload.severity,
            notes=payload.notes,
            is_active=payload.is_active,
        )
        return MutationResponse()

    return router
