"""훈련 계획 오케스트레이터"""
import time
from datetime import datetime
from typing import Optional
from .container import ServiceContainer
from ..utils.logger import get_logger

logger = get_logger(__name__)


class TrainingOrchestrator:
    """훈련 계획 생성 및 동기화 오케스트레이터"""

    def __init__(self, container: ServiceContainer):
        """
        Args:
            container: ServiceContainer 인스턴스
        """
        self.container = container

    def run_once(self) -> bool:
        """전체 파이프라인 1회 실행

        Returns:
            성공 여부
        """
        logger.info(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 업데이트 시작...")

        try:
            # 대회 정보 로깅
            race = self.container.settings.race
            if race.has_goal:
                logger.info(f"목표 대회 설정됨: {race.date}")
                if race.distance:
                    logger.info(f" - 거리: {race.distance}")
                if race.goal_time:
                    logger.info(f" - 목표 시간: {race.goal_time}")
                if race.target_pace:
                    logger.info(f" - 타겟 페이스: {race.target_pace}")

            # 1. 로그인
            logger.info("Garmin 로그인 중...")
            self.container.garmin_client.login()

            # 2. 기존 워크아웃 정리
            logger.info("기존 Coach Gemini 워크아웃 정리 중...")
            self.container.garmin_client.cleanup_existing_workouts()

            # 3. 메트릭 수집
            logger.info("건강 및 퍼포먼스 데이터 수집 중...")
            metrics = self.container.garmin_client.get_advanced_metrics()

            # 4. 훈련 계획 생성
            logger.info("Gemini AI로 훈련 계획 생성 중...")
            plan = self.container.gemini_client.create_training_plan(
                metrics=metrics,
                race_config=self.container.settings.race,
                include_strength=self.container.settings.include_strength
            )

            if not plan:
                logger.error("계획 생성 실패")
                return False

            logger.info(f"\n훈련 계획 생성 완료! ({len(plan.plan)}일)")

            # 5. Garmin에 업로드
            logger.info("Garmin에 워크아웃 업로드 중...")
            for daily_plan in plan.plan:
                workout = daily_plan.workout

                if workout.is_rest:
                    logger.info(f"[{daily_plan.date}] 휴식")
                    continue

                logger.info(f"[{daily_plan.date}] {workout.workout_name}")

                try:
                    workout_id = self.container.garmin_client.workout_manager.create_workout(workout)
                    if workout_id:
                        self.container.garmin_client.workout_manager.schedule_workout(workout_id, daily_plan.date)
                    time.sleep(1)  # API 부하 방지
                except Exception as e:
                    logger.error(f"워크아웃 업로드 실패: {e}")

            # 6. Google Calendar 동기화
            logger.info("Google Calendar 동기화 중...")
            try:
                self.container.calendar_client.authenticate()
                self.container.calendar_client.sync_service.sync(plan)
            except Exception as e:
                logger.warning(f"Google Calendar 동기화 실패 (계속 진행): {e}")

            logger.info("\n업데이트 완료")
            return True

        except Exception as e:
            logger.error(f"파이프라인 실패: {e}", exc_info=True)
            return False
