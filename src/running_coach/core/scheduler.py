"""스케줄링 서비스"""

import time
from collections.abc import Callable

import schedule

from ..config.constants import APP_NAME
from ..utils.logger import get_logger

logger = get_logger(__name__)


class SchedulerService:
    """스케줄링 서비스"""

    def __init__(
        self,
        run_job: Callable[[], object],
        *,
        schedule_times: list[str],
        run_mode: str,
        include_strength: bool,
        poll_interval_minutes: int | None = None,
    ):
        """
        Args:
            run_job: 예약 시 실행할 작업
            schedule_times: HH:MM 실행 시각 목록
            run_mode: plan 또는 auto
            include_strength: 근력운동 포함 여부
        """
        self.run_job = run_job
        self.schedule_times = schedule_times
        self.run_mode = run_mode
        self.include_strength = include_strength
        self.poll_interval_minutes = poll_interval_minutes

    def run(self) -> None:
        """서비스 모드 실행"""
        logger.info("--- %s: Advanced Adaptive Trainer ---", APP_NAME)
        if self.poll_interval_minutes is not None:
            logger.info(
                "서비스 모드 실행 중. %s분마다 due 사용자 작업을 claim함.",
                self.poll_interval_minutes,
            )
        else:
            logger.info(f"서비스 모드 실행 중. 매일 {', '.join(self.schedule_times)}에 예약됨.")
        logger.info(f"실행 모드: {self.run_mode}")
        logger.info(f"근력운동 포함: {self.include_strength}")

        self._register_jobs()

        logger.info(f"스케줄러 시작됨. 다음 실행: {schedule.next_run()}")

        # 무한 루프
        while True:
            schedule.run_pending()
            time.sleep(60)  # schedule 라이브러리의 pending job 체크 주기

    def _run_job(self) -> None:
        """스케줄된 작업 실행"""
        try:
            self.run_job()
        except Exception as e:
            logger.error(f"스케줄된 작업 실패: {e}", exc_info=True)

    def _register_jobs(self) -> None:
        """Register schedule jobs without starting the service loop."""
        if self.poll_interval_minutes is not None:
            schedule.every(self.poll_interval_minutes).minutes.do(self._run_job)
            return
        for target_time in self.schedule_times:
            schedule.every().day.at(target_time).do(self._run_job)
