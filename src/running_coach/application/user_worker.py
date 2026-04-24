"""Multi-user scheduled execution services."""

from __future__ import annotations

from dataclasses import dataclass

from ..models.user import RunSyncResponse, UserContext
from ..utils.logger import get_logger
from .user_service import UserApplicationService

logger = get_logger(__name__)


@dataclass(frozen=True)
class UserRunResult:
    """Result of one scheduled user run."""

    user_id: str
    external_key: str
    status: str
    mode: str
    error: str | None = None


@dataclass(frozen=True)
class MultiUserRunSummary:
    """Aggregate result for a multi-user scheduled pass."""

    total: int
    completed: int
    failed: int
    skipped: int
    results: list[UserRunResult]


class MultiUserWorker:
    """Runs scheduled coaching jobs for each runnable user."""

    def __init__(self, user_app: UserApplicationService):
        self.user_app = user_app

    def run_all(self, *, run_mode: str = "auto") -> MultiUserRunSummary:
        contexts = self.user_app.list_runnable_user_contexts()
        logger.info("다중 사용자 실행 시작: 대상 %s명, 모드=%s", len(contexts), run_mode)

        results = [self._run_one(context, run_mode=run_mode) for context in contexts]
        completed = sum(1 for result in results if result.status == "completed")
        failed = sum(1 for result in results if result.status == "failed")
        skipped = sum(1 for result in results if result.status == "skipped")

        logger.info(
            "다중 사용자 실행 완료: 완료=%s, 실패=%s, 건너뜀=%s",
            completed,
            failed,
            skipped,
        )
        return MultiUserRunSummary(
            total=len(results),
            completed=completed,
            failed=failed,
            skipped=skipped,
            results=results,
        )

    def _run_one(self, context: UserContext, *, run_mode: str) -> UserRunResult:
        try:
            response = self.user_app.run_user_sync(context.user_id, run_mode=run_mode)
            return self._result_from_response(context, response)
        except Exception as exc:
            logger.error(
                "사용자 실행 실패: user_id=%s external_key=%s error=%s",
                context.user_id,
                context.external_key,
                exc,
                exc_info=True,
            )
            return UserRunResult(
                user_id=context.user_id,
                external_key=context.external_key,
                status="failed",
                mode=run_mode,
                error=str(exc),
            )

    def _result_from_response(
        self,
        context: UserContext,
        response: RunSyncResponse,
    ) -> UserRunResult:
        return UserRunResult(
            user_id=context.user_id,
            external_key=context.external_key,
            status=response.status,
            mode=response.mode,
        )
