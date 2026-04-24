"""Multi-user scheduled execution services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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

        results = [
            self._run_one(context, run_mode=self._effective_run_mode(context, run_mode))
            for context in contexts
        ]
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

    def run_due(
        self,
        *,
        run_mode: str = "auto",
        now: datetime | None = None,
    ) -> MultiUserRunSummary:
        contexts = self.user_app.list_runnable_user_contexts()
        reference_time = now or datetime.now(timezone.utc)
        results: list[UserRunResult] = []

        for context in contexts:
            effective_run_mode = self._effective_run_mode(context, run_mode)
            if not self._is_due(context, reference_time):
                results.append(
                    UserRunResult(
                        user_id=context.user_id,
                        external_key=context.external_key,
                        status="skipped",
                        mode=effective_run_mode,
                    )
                )
                continue
            results.append(self._run_one(context, run_mode=effective_run_mode))

        completed = sum(1 for result in results if result.status == "completed")
        failed = sum(1 for result in results if result.status == "failed")
        skipped = sum(1 for result in results if result.status == "skipped")
        logger.info(
            "사용자별 스케줄 확인 완료: 대상=%s, 실행=%s, 실패=%s, 건너뜀=%s",
            len(results),
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

    def _is_due(self, context: UserContext, now: datetime) -> bool:
        try:
            local_time = now.astimezone(ZoneInfo(context.timezone))
        except ZoneInfoNotFoundError:
            logger.warning(
                "알 수 없는 사용자 timezone으로 실행 건너뜀: user_id=%s timezone=%s",
                context.user_id,
                context.timezone,
            )
            return False
        schedule_times = _parse_schedule_times(context.schedule_times)
        return f"{local_time.hour:02d}:{local_time.minute:02d}" in schedule_times

    def _effective_run_mode(self, context: UserContext, fallback: str) -> str:
        return context.run_mode or fallback


def _parse_schedule_times(raw_value: str) -> set[str]:
    normalized: set[str] = set()
    for raw_time in [item.strip() for item in raw_value.split(",") if item.strip()]:
        if ":" in raw_time:
            hour_text, minute_text = raw_time.split(":", 1)
        else:
            hour_text, minute_text = raw_time, "00"
        try:
            hour = int(hour_text)
            minute = int(minute_text)
        except ValueError:
            continue
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            normalized.add(f"{hour:02d}:{minute:02d}")
    return normalized
