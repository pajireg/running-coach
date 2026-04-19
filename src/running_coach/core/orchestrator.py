"""훈련 계획 오케스트레이터"""

import time
from datetime import date, datetime

from ..utils.logger import get_logger
from .container import ServiceContainer

logger = get_logger(__name__)


class TrainingOrchestrator:
    """훈련 계획 생성 및 동기화 오케스트레이터"""

    def __init__(self, container: ServiceContainer):
        """
        Args:
            container: ServiceContainer 인스턴스
        """
        self.container = container

    def run_once(self, run_mode: str = "plan") -> bool:
        """전체 파이프라인 1회 실행

        Returns:
            성공 여부
        """
        logger.info(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 업데이트 시작...")
        logger.info(f"실행 모드: {run_mode}")

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

            # 2. 메트릭 수집
            logger.info("건강 및 퍼포먼스 데이터 수집 중...")
            metrics = self.container.garmin_client.get_advanced_metrics()
            self._persist_daily_history(metrics)
            self._backfill_planned_history(metrics.date)
            self._persist_activity_history()
            self._rebuild_recent_executions(metrics.date)
            training_background = self._training_background(metrics.date)

            if run_mode == "auto" and not self._should_generate_plan(metrics.date):
                logger.info("새 재계획 조건이 없어 기존 훈련 계획을 유지합니다.")
                self._sync_completed_activity_calendar(metrics.date)
                logger.info("\n업데이트 완료")
                return True

            # 3. 훈련 계획 생성
            logger.info("Gemini AI로 훈련 계획 생성 중...")
            plan = self.container.gemini_client.create_training_plan(
                metrics=metrics,
                race_config=self.container.settings.race,
                include_strength=self.container.settings.include_strength,
                training_background=training_background,
            )

            if not plan:
                logger.error("계획 생성 실패")
                return False

            logger.info(f"\n훈련 계획 생성 완료! ({len(plan.plan)}일)")
            existing_workout_ids = self._existing_garmin_workout_ids(plan)
            self._persist_plan_history(metrics, plan, training_background)

            # 4. 기존 워크아웃 정리
            logger.info("기존 Running Coach 워크아웃 정리 중...")
            self.container.garmin_client.cleanup_existing_workouts(
                workout_ids=existing_workout_ids or None
            )
            self._clear_garmin_sync_results(plan)

            # 5. Garmin에 업로드
            logger.info("Garmin에 워크아웃 업로드 중...")
            workout_manager = self.container.garmin_client.workout_manager
            assert workout_manager is not None
            for daily_plan in plan.plan:
                workout = daily_plan.workout

                if workout.is_rest:
                    logger.info(f"[{daily_plan.date}] 휴식")
                    continue

                logger.info(f"[{daily_plan.date}] {workout.workout_name}")

                try:
                    workout_id = workout_manager.create_workout(workout)
                    if workout_id:
                        workout_manager.schedule_workout(workout_id, daily_plan.date)
                        self._persist_garmin_sync_result(
                            workout_date=daily_plan.date,
                            garmin_workout_id=workout_id,
                            garmin_schedule_status="scheduled",
                        )
                    else:
                        self._persist_garmin_sync_result(
                            workout_date=daily_plan.date,
                            garmin_workout_id=None,
                            garmin_schedule_status="upload_failed",
                        )
                    time.sleep(1)  # API 부하 방지
                except Exception as e:
                    self._persist_garmin_sync_result(
                        workout_date=daily_plan.date,
                        garmin_workout_id=None,
                        garmin_schedule_status=f"error: {str(e)[:90]}",
                    )
                    logger.error(f"워크아웃 업로드 실패: {e}")

            self._sync_google_calendar(plan, metrics.date)

            logger.info("\n업데이트 완료")
            return True

        except Exception as e:
            logger.error(f"파이프라인 실패: {e}", exc_info=True)
            return False

    def _persist_daily_history(self, metrics) -> None:
        """전문 코치용 히스토리 저장."""
        if not self.container.settings.persist_history:
            return

        try:
            self.container.history_service.db.ping()
            self.container.history_service.ensure_athlete(
                garmin_email=self.container.settings.garmin_email,
                max_heart_rate=self.container.settings.max_heart_rate,
            )
            self.container.history_service.record_daily_metrics(metrics)
        except Exception as e:
            logger.warning(f"히스토리 저장 실패 (계속 진행): {e}")

    def _persist_plan_history(self, metrics, plan, training_background) -> None:
        """계획 및 코치 의사결정 저장."""
        if not self.container.settings.persist_history:
            return

        try:
            self.container.history_service.record_training_plan(plan)
            summary = (
                f"{metrics.performance.training_load.status} 상태에서 "
                f"{plan.total_workouts}개 세션 계획 생성"
            )
            self.container.history_service.record_coach_decision(
                decision_date=metrics.date,
                summary=summary,
                metrics=metrics,
                plan=plan,
                training_background=training_background,
            )
        except Exception as e:
            logger.warning(f"계획 히스토리 저장 실패 (계속 진행): {e}")

    def _persist_activity_history(self) -> None:
        """최근 활동 히스토리 저장."""
        if not self.container.settings.persist_history:
            return

        try:
            activities = self.container.garmin_client.get_recent_activity_history()
            self.container.history_service.record_activities(activities)
        except Exception as e:
            logger.warning(f"활동 히스토리 저장 실패 (계속 진행): {e}")

    def _rebuild_recent_executions(self, as_of) -> None:
        """최근 execution 재매칭."""
        if not self.container.settings.persist_history:
            return

        try:
            rebuilt = self.container.history_service.rebuild_recent_workout_executions(as_of=as_of)
            logger.info(f"최근 workout execution 재계산 완료: {rebuilt} 개")
        except Exception as e:
            logger.warning(f"최근 workout execution 재계산 실패 (계속 진행): {e}")

    def _backfill_planned_history(self, as_of) -> None:
        """Garmin 캘린더의 과거 계획 백필."""
        if not self.container.settings.persist_history:
            return

        try:
            scheduled_items = self.container.garmin_client.get_recent_scheduled_workout_history(
                target_date=as_of
            )
            inserted = self.container.history_service.backfill_planned_workouts(scheduled_items)
            logger.info(f"과거 planned workout 백필 완료: {inserted} 개")
        except Exception as e:
            logger.warning(f"과거 planned workout 백필 실패 (계속 진행): {e}")

    def _training_background(self, as_of):
        """장기 훈련 배경 요약."""
        if not self.container.settings.persist_history:
            return None
        try:
            return self.container.history_service.summarize_training_background(as_of)
        except Exception as e:
            logger.warning(f"훈련 배경 요약 실패 (계속 진행): {e}")
            return None

    def _existing_garmin_workout_ids(self, plan) -> list[str]:
        """새 계획 범위의 기존 Garmin workout id 조회."""
        if not self.container.settings.persist_history:
            return []
        try:
            return self.container.history_service.list_planned_garmin_workout_ids(
                start_date=plan.start_date,
                end_date=plan.end_date,
            )
        except Exception as e:
            logger.warning(f"기존 Garmin workout id 조회 실패 (prefix fallback 사용): {e}")
            return []

    def _clear_garmin_sync_results(self, plan) -> None:
        """삭제된 이전 Garmin workout id를 계획 범위에서 초기화."""
        if not self.container.settings.persist_history:
            return
        try:
            self.container.history_service.clear_garmin_sync_results(
                start_date=plan.start_date,
                end_date=plan.end_date,
            )
        except Exception as e:
            logger.warning(f"Garmin sync 결과 초기화 실패 (계속 진행): {e}")

    def _persist_garmin_sync_result(
        self,
        workout_date,
        garmin_workout_id: str | None,
        garmin_schedule_status: str,
    ) -> None:
        """Garmin 업로드 결과 저장."""
        if not self.container.settings.persist_history:
            return

        try:
            self.container.history_service.record_garmin_sync_result(
                workout_date=workout_date,
                garmin_workout_id=garmin_workout_id,
                garmin_schedule_status=garmin_schedule_status,
            )
        except Exception as e:
            logger.warning(f"Garmin 동기화 결과 저장 실패 (계속 진행): {e}")

    def _should_generate_plan(self, as_of) -> bool:
        """auto 모드에서 LLM 계획 생성이 필요한지 판단."""
        if not self.container.settings.persist_history:
            logger.info("히스토리 저장이 꺼져 있어 auto 모드에서도 계획을 생성합니다.")
            return True

        try:
            freshness = self.container.history_service.summarize_plan_freshness(
                as_of=self._coerce_date(as_of),
            )
        except Exception as e:
            logger.warning(f"계획 freshness 판단 실패로 재계획을 진행합니다: {e}")
            return True

        logger.info(
            (
                "계획 freshness: active=%s, new_activity=%s, recovery_change=%s, missed=%s, "
                "last_plan=%s, latest_activity=%s"
            ),
            freshness["hasActivePlan"],
            freshness["hasNewActivitySinceLastPlan"],
            freshness.get("recoveryShiftReasons", []),
            freshness.get("missedWorkoutCount", 0),
            freshness["lastPlanCreatedAt"],
            freshness["latestActivityCreatedAt"],
        )
        return bool(freshness["shouldGeneratePlan"])

    def _sync_google_calendar(self, plan, as_of) -> None:
        """계획과 실제 운동 기록을 Google Calendar에 동기화."""
        logger.info("Google Calendar 동기화 중...")
        try:
            service = self.container.calendar_client.authenticate()
            if service is None:
                logger.info("Google Calendar 인증 정보가 없어 동기화를 건너뜁니다.")
                return
            sync_service = self.container.calendar_client.sync_service
            assert sync_service is not None
            sync_service.sync(plan)
            self._sync_completed_activity_calendar(as_of)
        except Exception as e:
            logger.warning(f"Google Calendar 동기화 실패 (계속 진행): {e}")

    def _sync_completed_activity_calendar(self, as_of) -> None:
        """실제 운동 기록 캘린더를 증분 동기화."""
        try:
            service = self.container.calendar_client.authenticate()
            if service is None:
                return
            sync_service = self.container.calendar_client.sync_service
            assert sync_service is not None
            completed_activities = self.container.history_service.list_recent_completed_activities(
                as_of=self._coerce_date(as_of),
                days=2,
            )
            sync_service.sync_completed_activities(
                activities=completed_activities,
                as_of=self._coerce_date(as_of),
                days_back=2,
            )
        except Exception as e:
            logger.warning(f"실제 운동 기록 캘린더 동기화 실패 (계속 진행): {e}")

    @staticmethod
    def _coerce_date(value) -> date:
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value))
