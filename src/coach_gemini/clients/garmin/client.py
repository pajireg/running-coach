"""Garmin Connect 클라이언트"""
import os
from typing import Optional
from datetime import date as DateType
from garminconnect import Garmin
from ...models.metrics import AdvancedMetrics
from ...models.training import TrainingPlan, DailyPlan
from ...config.settings import Settings
from ...config.constants import GARMIN_TOKEN_DIR
from ...utils.logger import get_logger
from ...exceptions import GarminAuthenticationError, GarminError
from .health_collector import HealthDataCollector
from .performance_collector import PerformanceDataCollector
from .context_collector import ContextDataCollector
from .workout_manager import WorkoutManager

logger = get_logger(__name__)


class GarminClient:
    """Garmin Connect 클라이언트 (Facade)"""

    def __init__(self, email: str, password: str, settings: Settings):
        """
        Args:
            email: Garmin 계정 이메일
            password: Garmin 계정 비밀번호
            settings: Settings 인스턴스
        """
        self.email = email
        self.password = password
        self.settings = settings
        self._connection: Optional[Garmin] = None

        # Collector 및 Manager 초기화 (지연 초기화)
        self.health_collector: Optional[HealthDataCollector] = None
        self.performance_collector: Optional[PerformanceDataCollector] = None
        self.context_collector: Optional[ContextDataCollector] = None
        self.workout_manager: Optional[WorkoutManager] = None

    def login(self) -> None:
        """가민 커넥트 로그인"""
        if not self.email or not self.password:
            raise GarminAuthenticationError("Missing Garmin email or password")

        # 토큰 디렉토리 설정
        os.environ["GARMINTOKENS"] = str(GARMIN_TOKEN_DIR)

        if not GARMIN_TOKEN_DIR.exists():
            logger.warning(f"토큰 디렉토리 '{GARMIN_TOKEN_DIR}'가 없음")
            logger.warning("인증을 위해 'python setup_garmin.py'를 먼저 실행해야 함")

        try:
            self._connection = Garmin(self.email, self.password)
            self._connection.login()
            logger.info("로그인 성공!")

            # Collector 및 Manager 초기화
            self.health_collector = HealthDataCollector(self._connection)
            self.performance_collector = PerformanceDataCollector(self._connection, self.settings)
            self.context_collector = ContextDataCollector(self._connection)
            self.workout_manager = WorkoutManager(self._connection)

        except Exception as e:
            logger.error(f"로그인 실패: {e}")
            raise GarminAuthenticationError(f"Failed to login: {e}") from e

    def get_advanced_metrics(self, target_date: Optional[DateType] = None) -> AdvancedMetrics:
        """통합 메트릭 수집 - 기존 get_advanced_metrics() 대체

        Args:
            target_date: 수집할 날짜 (기본값: 오늘)

        Returns:
            AdvancedMetrics 모델
        """
        if not self._connection:
            raise GarminError("Not logged in. Call login() first.")

        target_date = target_date or DateType.today()

        logger.info("상세 건강 및 퍼포먼스 데이터 수집 중...")

        return AdvancedMetrics(
            date=target_date,
            health=self.health_collector.collect(target_date),
            performance=self.performance_collector.collect(target_date),
            context=self.context_collector.collect(target_date)
        )

    def upload_training_plan(self, plan: TrainingPlan) -> None:
        """훈련 계획을 Garmin에 업로드 및 예약

        Args:
            plan: TrainingPlan 모델
        """
        if not self._connection:
            raise GarminError("Not logged in. Call login() first.")

        logger.info(f"훈련 계획 업로드 중: {len(plan.plan)}일")

        for daily_plan in plan.plan:
            workout = daily_plan.workout

            # 휴식 워크아웃은 건너뛰기
            if workout.is_rest:
                logger.info(f"{daily_plan.date}: 휴식 - 건너뜀")
                continue

            try:
                # 워크아웃 생성
                workout_id = self.workout_manager.create_workout(workout)

                if workout_id:
                    # 워크아웃 예약
                    self.workout_manager.schedule_workout(workout_id, daily_plan.date)
                else:
                    logger.warning(f"{daily_plan.date}: 워크아웃 생성 실패")

            except Exception as e:
                logger.error(f"{daily_plan.date}: 워크아웃 업로드 실패 - {e}")

    def cleanup_existing_workouts(self) -> int:
        """기존 Coach Gemini 워크아웃 정리

        Returns:
            삭제된 워크아웃 개수
        """
        if not self._connection:
            raise GarminError("Not logged in. Call login() first.")

        return self.workout_manager.delete_gemini_workouts()

    @property
    def is_logged_in(self) -> bool:
        """로그인 상태 확인"""
        return self._connection is not None
