"""Garmin Connect 클라이언트"""

import os
from datetime import date, datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from garminconnect import Garmin  # type: ignore[import-untyped]

from ...config.constants import GARMIN_TOKEN_DIR, SUPPORTED_WORKOUT_PREFIXES, TIMEZONE
from ...config.settings import Settings
from ...exceptions import GarminAuthenticationError, GarminError
from ...models.metrics import AdvancedMetrics
from ...models.training import TrainingPlan
from ...utils.logger import get_logger
from .context_collector import ContextDataCollector
from .health_collector import HealthDataCollector
from .performance_collector import PerformanceDataCollector
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
            self._connection = Garmin(
                self.email,
                self.password,
                prompt_mfa=lambda: input("Garmin MFA 코드 입력: ").strip(),
            )

            try:
                self._connection.login(str(GARMIN_TOKEN_DIR))
            except TypeError:
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

    def get_advanced_metrics(self, target_date: Optional[date] = None) -> AdvancedMetrics:
        """통합 메트릭 수집 - 기존 get_advanced_metrics() 대체

        Args:
            target_date: 수집할 날짜 (기본값: 오늘)

        Returns:
            AdvancedMetrics 모델
        """
        if not self._connection:
            raise GarminError("Not logged in. Call login() first.")

        target_date = target_date or date.today()

        logger.info("상세 건강 및 퍼포먼스 데이터 수집 중...")
        assert self.health_collector is not None
        assert self.performance_collector is not None
        assert self.context_collector is not None

        return AdvancedMetrics(
            date=target_date,
            health=self.health_collector.collect(target_date),
            performance=self.performance_collector.collect(target_date),
            context=self.context_collector.collect(target_date),
        )

    def upload_training_plan(self, plan: TrainingPlan) -> None:
        """훈련 계획을 Garmin에 업로드 및 예약

        Args:
            plan: TrainingPlan 모델
        """
        if not self._connection:
            raise GarminError("Not logged in. Call login() first.")

        logger.info(f"훈련 계획 업로드 중: {len(plan.plan)}일")
        assert self.workout_manager is not None

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

    def cleanup_existing_workouts(self, workout_ids: Optional[list[str]] = None) -> int:
        """기존 Running Coach 워크아웃 정리

        Returns:
            삭제된 워크아웃 개수
        """
        if not self._connection:
            raise GarminError("Not logged in. Call login() first.")

        assert self.workout_manager is not None
        return self.workout_manager.delete_generated_workouts(workout_ids=workout_ids)

    def get_recent_activity_history(self, days: int = 42, limit: int = 200) -> list[dict[str, Any]]:
        """최근 활동 이력을 상세/랩 정보와 함께 반환."""
        if not self._connection:
            raise GarminError("Not logged in. Call login() first.")

        activities = self._connection.get_activities(0, limit)
        cutoff = datetime.now(ZoneInfo(TIMEZONE)) - timedelta(days=days)
        history: list[dict[str, Any]] = []

        for activity in activities:
            start_time = self._parse_start_time(activity.get("startTimeLocal"))
            if start_time is not None and start_time < cutoff:
                continue

            activity_id = activity.get("activityId")
            details: dict[str, Any] = {}
            splits: list[dict[str, Any]] = []

            if activity_id is not None:
                try:
                    details = self._connection.get_activity_details(activity_id)
                except Exception as e:
                    logger.warning(f"활동 상세 수집 실패 ({activity_id}): {e}")

                try:
                    raw_splits = self._connection.get_activity_splits(activity_id)
                    if isinstance(raw_splits, list):
                        splits = [split for split in raw_splits if isinstance(split, dict)]
                    elif isinstance(raw_splits, dict):
                        lap_dtos = raw_splits.get("lapDTOs", [])
                        if isinstance(lap_dtos, list):
                            splits = [split for split in lap_dtos if isinstance(split, dict)]
                except Exception as e:
                    logger.warning(f"활동 split 수집 실패 ({activity_id}): {e}")

            history.append(
                {
                    "summary": activity,
                    "details": details,
                    "splits": splits,
                }
            )

        logger.info(f"최근 활동 히스토리 수집 완료: {len(history)} 개")
        return history

    def get_recent_scheduled_workout_history(
        self, target_date: Optional[date] = None, days: int = 84
    ) -> list[dict[str, Any]]:
        """최근 Garmin 캘린더의 Running Coach 워크아웃 이력."""
        if not self._connection:
            raise GarminError("Not logged in. Call login() first.")

        target_date = target_date or date.today()
        cutoff = target_date - timedelta(days=days)
        months_to_fetch: list[tuple[int, int]] = []
        cursor = target_date.replace(day=1)
        while len(months_to_fetch) < 6:
            months_to_fetch.append((cursor.year, cursor.month))
            cursor = (cursor - timedelta(days=1)).replace(day=1)

        schedule_items: list[dict[str, Any]] = []
        seen_ids: set[Any] = set()
        for year_value, month_value in months_to_fetch:
            try:
                payload = self._connection.get_scheduled_workouts(year_value, month_value)
            except Exception as e:
                logger.warning(
                    f"과거 워크아웃 캘린더 수집 실패 ({year_value}-{month_value:02d}): {e}"
                )
                continue
            if not isinstance(payload, dict):
                continue
            for item in payload.get("calendarItems", []):
                if not isinstance(item, dict):
                    continue
                item_id = item.get("id")
                if item_id in seen_ids:
                    continue
                item_date_raw = item.get("date")
                title = str(item.get("title") or "")
                if not item_date_raw or not any(
                    title.startswith(f"{prefix}:") for prefix in SUPPORTED_WORKOUT_PREFIXES
                ):
                    continue
                item_date = date.fromisoformat(item_date_raw)
                if not (cutoff <= item_date <= target_date):
                    continue
                if item.get("itemType") != "workout":
                    continue
                seen_ids.add(item_id)
                schedule_items.append(item)

        schedule_items.sort(key=lambda item: str(item.get("date")))
        logger.info(f"최근 예약 워크아웃 백필 수집 완료: {len(schedule_items)} 개")
        return schedule_items

    @staticmethod
    def _parse_start_time(value: Any) -> Optional[datetime]:
        """Garmin 시간 문자열을 datetime으로 변환."""
        if not value or not isinstance(value, str):
            return None
        normalized = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=ZoneInfo(TIMEZONE))
            return parsed
        except ValueError:
            return None

    @property
    def is_logged_in(self) -> bool:
        """로그인 상태 확인"""
        return self._connection is not None
