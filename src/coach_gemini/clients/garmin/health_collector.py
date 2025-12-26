"""건강 데이터 수집기"""
from typing import Optional
from datetime import date as DateType
from ...models.health import HealthMetrics, SleepDetails
from ...utils.logger import get_logger
from ...utils.time_utils import format_seconds
from .utils import safe_get

logger = get_logger(__name__)


class HealthDataCollector:
    """건강 데이터 수집기"""

    def __init__(self, garmin_connection):
        """
        Args:
            garmin_connection: garminconnect.Garmin 인스턴스
        """
        self.garmin = garmin_connection

    def collect(self, target_date: DateType) -> HealthMetrics:
        """건강 지표 수집 (통합)

        Args:
            target_date: 수집할 날짜

        Returns:
            HealthMetrics 모델
        """
        logger.info("건강 데이터 수집 중...")
        date_str = target_date.isoformat()

        return HealthMetrics(
            steps=self._get_steps(date_str),
            sleep_score=self._get_sleep_score(date_str),
            sleep_details=self._get_sleep_details(date_str),
            resting_hr=self._get_resting_hr(date_str),
            body_battery=self._get_body_battery(date_str),
            hrv=self._get_hrv(date_str)
        )

    def _get_steps(self, date_str: str) -> Optional[int]:
        """걸음 수 수집"""
        try:
            stats = self.garmin.get_user_summary(date_str)
            steps = stats.get('totalSteps', 0)
            logger.debug(f"걸음 수: {steps}")
            return steps
        except Exception as e:
            logger.warning(f"걸음 수 수집 실패: {e}")
            return None

    def _get_sleep_score(self, date_str: str) -> Optional[int]:
        """수면 점수 수집"""
        try:
            s_data = self.garmin.get_sleep_data(date_str)
            score = safe_get(s_data, 'dailySleepDTO', 'sleepScores', 'overall', 'value')
            return score
        except Exception as e:
            logger.warning(f"수면 점수 수집 실패: {e}")
            return None

    def _get_sleep_details(self, date_str: str) -> Optional[SleepDetails]:
        """수면 상세 정보 수집"""
        try:
            s_data = self.garmin.get_sleep_data(date_str)
            dto = s_data.get('dailySleepDTO', {})
            scores = safe_get(dto, 'sleepScores', 'overall', default={})

            score = scores.get('value')
            if not score:
                return None

            sleep_details = SleepDetails(
                score=score,
                quality=scores.get('qualifierKey'),
                duration=format_seconds(dto.get('sleepTimeSeconds')),
                deep=format_seconds(dto.get('deepSleepSeconds')),
                light=format_seconds(dto.get('lightSleepSeconds')),
                rem=format_seconds(dto.get('remSleepSeconds')),
                awake=format_seconds(dto.get('awakeSleepSeconds'))
            )

            logger.debug(f"수면 상세: {sleep_details.formatted_info}")
            return sleep_details

        except Exception as e:
            logger.warning(f"수면 상세 정보 수집 실패: {e}")
            return None

    def _get_resting_hr(self, date_str: str) -> Optional[int]:
        """안정시 심박수 수집"""
        try:
            stats = self.garmin.get_user_summary(date_str)
            rhr = stats.get('restingHeartRate')
            if rhr:
                logger.debug(f"안정시 심박수: {rhr}")
            return rhr
        except Exception as e:
            logger.warning(f"안정시 심박수 수집 실패: {e}")
            return None

    def _get_body_battery(self, date_str: str) -> Optional[int]:
        """바디 배터리 수집"""
        try:
            bb_data = self.garmin.get_body_battery(date_str)
            bb_val = None

            if bb_data and isinstance(bb_data, list) and len(bb_data) > 0:
                last_entry = bb_data[-1]
                if 'bodyBatteryValuesArray' in last_entry:
                    values = last_entry['bodyBatteryValuesArray']
                    if values and len(values) > 0:
                        bb_val = values[-1][1]  # [timestamp, value]

            if bb_val:
                logger.debug(f"바디 배터리: {bb_val}")
            return bb_val

        except Exception as e:
            logger.warning(f"바디 배터리 수집 실패: {e}")
            return None

    def _get_hrv(self, date_str: str) -> Optional[int]:
        """HRV (심박 변이도) 수집"""
        try:
            hrv_data = self.garmin.get_hrv_data(date_str)
            # HRV 데이터 구조는 API 버전에 따라 다를 수 있음
            if hrv_data and isinstance(hrv_data, dict):
                hrv_val = hrv_data.get('lastNightAvg') or hrv_data.get('weeklyAvg')
                if hrv_val:
                    logger.debug(f"HRV: {hrv_val}")
                return hrv_val
            return None
        except Exception as e:
            logger.warning(f"HRV 수집 실패: {e}")
            return None
