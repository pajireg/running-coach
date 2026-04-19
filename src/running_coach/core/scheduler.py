"""스케줄링 서비스"""

import time

import schedule

from ..config.constants import APP_NAME
from ..config.settings import Settings
from ..utils.logger import get_logger
from .orchestrator import TrainingOrchestrator

logger = get_logger(__name__)


class SchedulerService:
    """스케줄링 서비스"""

    def __init__(self, orchestrator: TrainingOrchestrator, settings: Settings):
        """
        Args:
            orchestrator: TrainingOrchestrator 인스턴스
            settings: Settings 인스턴스
        """
        self.orchestrator = orchestrator
        self.settings = settings

    def run(self) -> None:
        """서비스 모드 실행"""
        target_times = self.settings.parsed_schedule_times()

        logger.info("--- %s: Advanced Adaptive Trainer ---", APP_NAME)
        logger.info(f"서비스 모드 실행 중. 매일 {', '.join(target_times)}에 예약됨.")
        logger.info(f"실행 모드: {self.settings.service_run_mode}")
        logger.info(f"근력운동 포함: {self.settings.include_strength}")

        # 스케줄 등록
        for target_time in target_times:
            schedule.every().day.at(target_time).do(self._run_job)

        logger.info(f"스케줄러 시작됨. 다음 실행: {schedule.next_run()}")

        # 무한 루프
        while True:
            schedule.run_pending()
            time.sleep(60)  # 1분마다 스케줄 체크

    def _run_job(self) -> None:
        """스케줄된 작업 실행"""
        try:
            self.orchestrator.run_once(run_mode=self.settings.service_run_mode)
        except Exception as e:
            logger.error(f"스케줄된 작업 실패: {e}", exc_info=True)
