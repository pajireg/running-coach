"""활동 컨텍스트 데이터 수집기"""

from datetime import date, datetime, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

from ...config.constants import TIMEZONE
from ...models.context import Activity, ActivityContext, MonthlyStats, ScheduleItem
from ...utils.logger import get_logger

logger = get_logger(__name__)

RUNNING_TYPES = {"running", "treadmill_running", "trail_running"}
CROSS_TRAINING_TYPES = {
    "cycling",
    "indoor_cycling",
    "mountaineering",
    "hiking",
    "walking",
    "road_biking",
    "gravel_cycling",
}


class ContextDataCollector:
    """활동 컨텍스트 데이터 수집기"""

    def __init__(self, garmin_connection):
        """
        Args:
            garmin_connection: garminconnect.Garmin 인스턴스
        """
        self.garmin = garmin_connection

    def collect(self, target_date: date) -> ActivityContext:
        """컨텍스트 수집 (통합)

        Args:
            target_date: 기준 날짜

        Returns:
            ActivityContext 모델
        """
        logger.info("활동 컨텍스트 수집 중...")

        current_schedule = self._get_30day_schedule(target_date)
        yesterday = target_date - timedelta(days=1)
        running_activities = self._get_recent_running_activities(target_date)
        cross_training_activities = self._get_recent_cross_training_activities(target_date)
        recent_7d_cutoff = target_date - timedelta(days=6)
        recent_7d_activities = [
            activity
            for activity in running_activities
            if activity.date is not None and activity.date >= recent_7d_cutoff
        ]
        recent_7d_run_distance_km = sum(
            activity.distance or 0.0 for activity in recent_7d_activities
        )
        recent_30d_run_distance_km = sum(
            activity.distance or 0.0 for activity in running_activities
        )
        recent_7d_cross_training = [
            activity
            for activity in cross_training_activities
            if activity.date is not None and activity.date >= recent_7d_cutoff
        ]

        return ActivityContext(
            yesterday_actual=self._get_yesterday_activities(target_date),
            yesterday_planned=[
                item
                for item in current_schedule
                if item.type == "workout" and item.date == yesterday
            ],
            current_schedule=current_schedule,
            yearly_trend=self._get_yearly_trend(),
            recent_7d_run_distance_km=recent_7d_run_distance_km,
            recent_30d_run_distance_km=recent_30d_run_distance_km,
            recent_30d_run_count=len(running_activities),
            recent_7d_non_running_duration_minutes=int(
                sum((activity.duration or 0.0) for activity in recent_7d_cross_training) / 60
            ),
            recent_7d_non_running_sessions=len(recent_7d_cross_training),
            recent_7d_non_running_types=sorted(
                {activity.type for activity in recent_7d_cross_training if activity.type}
            ),
        )

    def _get_yesterday_activities(self, target_date: date) -> List[Activity]:
        """어제 활동 내역 (라인 285-300)

        Args:
            target_date: 기준 날짜

        Returns:
            어제 활동 목록
        """
        try:
            yesterday = target_date - timedelta(days=1)
            yesterday_str = yesterday.isoformat()

            yesterday_acts = self.garmin.get_activities_by_date(yesterday_str, yesterday_str)
            activities = []

            for act in yesterday_acts:
                activities.append(
                    Activity(
                        date=yesterday,
                        name=act.get("activityName"),
                        type=(
                            act.get("activityType", {}).get("typeKey")
                            if isinstance(act.get("activityType"), dict)
                            else None
                        ),
                        distance=self._meters_to_km(act.get("distance")),
                        duration=act.get("duration"),
                        calories=act.get("calories"),
                    )
                )

            logger.info(f"어제 활동 내역 수집 완료: {len(activities)} 개의 활동")
            return activities

        except Exception as e:
            logger.warning(f"어제 활동 내역 수집 실패: {e}")
            return []

    def _get_30day_schedule(self, target_date: date) -> List[ScheduleItem]:
        """최근 30일 일정 (라인 302-369)

        Args:
            target_date: 기준 날짜

        Returns:
            최근 30일 일정 목록
        """
        try:
            thirty_days_ago = target_date - timedelta(days=30)

            # 최근 30일 범위를 안전하게 덮기 위해 최대 3개월 조회
            months_to_fetch: List[tuple[int, int]] = []
            cursor = target_date.replace(day=1)
            while len(months_to_fetch) < 3:
                months_to_fetch.append((cursor.year, cursor.month))
                cursor = (cursor - timedelta(days=1)).replace(day=1)

            all_items = []
            for y, m in months_to_fetch:
                try:
                    cal_data = self.garmin.get_scheduled_workouts(y, m)
                    if isinstance(cal_data, dict):
                        all_items.extend(cal_data.get("calendarItems", []))
                except Exception:
                    continue

            schedule_items = []
            seen_ids = set()  # 중복 처리용

            for item in all_items:
                item_id = item.get("id")
                if item_id in seen_ids:
                    continue

                item_date_str = item.get("date")
                if not item_date_str:
                    continue

                item_date = date.fromisoformat(item_date_str)

                # 최근 30일 이내인지 확인
                if thirty_days_ago <= item_date <= target_date:
                    item_type = item.get("itemType")
                    if item_type in ["workout", "activity"]:
                        summary = ""
                        if item_type == "activity":
                            raw_dist = item.get("activeSplitSummaryDistance") or item.get(
                                "distance"
                            )
                            dist_km = self._calendar_distance_to_km(raw_dist)

                            raw_dur = item.get("elapsedDuration") or (
                                self._calendar_duration_to_seconds(item.get("duration"))
                            )
                            h = int(raw_dur // 3600)
                            m = int((raw_dur % 3600) // 60)
                            s = int(raw_dur % 60)
                            dur_str = f"{h}h {m}m {s}s" if h > 0 else f"{m}m {s}s"

                            avg_hr = item.get("averageHR", "N/A")
                            summary = f"({dist_km}km, {dur_str}, HR: {avg_hr})"

                        schedule_items.append(
                            ScheduleItem(
                                date=item_date,
                                title=item.get("title") or "",
                                type=item_type,
                                details=summary,
                            )
                        )
                        seen_ids.add(item_id)

            # 날짜순 정렬
            schedule_items.sort(key=lambda x: x.date)

            logger.info(f"최근 30일 훈련 및 활동 수집 완료: {len(schedule_items)} 개의 항목")
            return schedule_items

        except Exception as e:
            logger.warning(f"최근 일정 수집 실패: {e}")
            return []

    def _get_recent_running_activities(self, target_date: date) -> List[Activity]:
        """최근 30일 러닝 활동 요약."""
        try:
            cutoff = datetime.combine(
                target_date - timedelta(days=30),
                datetime.min.time(),
                tzinfo=ZoneInfo(TIMEZONE),
            )
            all_activities = self.garmin.get_activities(0, 200)
            running_activities: List[Activity] = []

            for act in all_activities:
                start_time = self._parse_start_time(act.get("startTimeLocal"))
                if start_time is None or start_time.date() > target_date:
                    continue
                if start_time < cutoff:
                    continue

                activity_type = act.get("activityType", {})
                type_key = activity_type.get("typeKey") if isinstance(activity_type, dict) else None
                if type_key not in RUNNING_TYPES:
                    continue

                running_activities.append(
                    Activity(
                        date=start_time.date(),
                        name=act.get("activityName"),
                        type=type_key,
                        distance=self._meters_to_km(act.get("distance")),
                        duration=act.get("duration"),
                        calories=act.get("calories"),
                    )
                )

            return running_activities
        except Exception as e:
            logger.warning(f"최근 러닝 활동 수집 실패: {e}")
            return []

    def _get_recent_cross_training_activities(self, target_date: date) -> List[Activity]:
        """최근 7일 비러닝 크로스트레이닝 요약."""
        try:
            cutoff = datetime.combine(
                target_date - timedelta(days=7),
                datetime.min.time(),
                tzinfo=ZoneInfo(TIMEZONE),
            )
            all_activities = self.garmin.get_activities(0, 200)
            cross_training: List[Activity] = []

            for act in all_activities:
                start_time = self._parse_start_time(act.get("startTimeLocal"))
                if start_time is None or start_time.date() > target_date:
                    continue
                if start_time < cutoff:
                    continue

                activity_type = act.get("activityType", {})
                type_key = activity_type.get("typeKey") if isinstance(activity_type, dict) else None
                if type_key not in CROSS_TRAINING_TYPES:
                    continue

                cross_training.append(
                    Activity(
                        date=start_time.date(),
                        name=act.get("activityName"),
                        type=type_key,
                        distance=self._meters_to_km(act.get("distance")),
                        duration=act.get("duration"),
                        calories=act.get("calories"),
                    )
                )

            return cross_training
        except Exception as e:
            logger.warning(f"최근 크로스트레이닝 수집 실패: {e}")
            return []

    def _get_yearly_trend(self) -> List[MonthlyStats]:
        """연간 통계 (라인 371-404)

        Returns:
            월별 통계 목록
        """
        try:
            # 최근 1년치 활동 리스트 가져오기 (최대 500개)
            all_activities = self.garmin.get_activities(0, 500)
            yearly_stats = {}  # {(year, month): {"dist": 0, "count": 0}}

            limit_date = datetime.now(ZoneInfo(TIMEZONE)) - timedelta(days=365)

            for act in all_activities:
                start_time_str = act.get("startTimeLocal")
                if not start_time_str:
                    continue

                start_time = self._parse_start_time(start_time_str)
                if start_time is None:
                    continue

                if start_time < limit_date:
                    break  # 1년 이전 데이터면 조기 종료

                key = (start_time.year, start_time.month)
                if key not in yearly_stats:
                    yearly_stats[key] = {"dist": 0, "count": 0}

                yearly_stats[key]["dist"] += act.get("distance", 0) / 1000
                yearly_stats[key]["count"] += 1

            # 보기 좋게 정렬
            sorted_keys = sorted(yearly_stats.keys(), reverse=True)
            monthly_stats = []

            for y, m in sorted_keys:
                s = yearly_stats[(y, m)]
                monthly_stats.append(
                    MonthlyStats(year=y, month=m, distance_km=s["dist"], activity_count=s["count"])
                )

            logger.info(f"연간 훈련 요약 수집 완료: {len(monthly_stats)} 개월 데이터")
            return monthly_stats

        except Exception as e:
            logger.warning(f"연간 요약 수집 실패: {e}")
            return []

    @staticmethod
    def _meters_to_km(distance_meters) -> Optional[float]:
        """미터 단위를 킬로미터로 변환"""
        if distance_meters is None:
            return None
        return round(float(distance_meters) / 1000, 2)

    @staticmethod
    def _extract_distance_km(details: str) -> float:
        """상세 문자열에서 거리 추출"""
        if not details:
            return 0.0
        prefix = details.split("km", 1)[0]
        try:
            return float(prefix.strip(" ("))
        except ValueError:
            return 0.0

    @staticmethod
    def _calendar_distance_to_km(value) -> float:
        """캘린더 distance를 km로 정규화."""
        if not value:
            return 0.0
        raw = float(value)
        if raw >= 100000:
            return round(raw / 100000, 2)
        if raw >= 1000:
            return round(raw / 1000, 2)
        return round(raw, 2)

    @staticmethod
    def _calendar_duration_to_seconds(value) -> float:
        """캘린더 duration 값을 초 단위로 정규화."""
        if not value:
            return 0.0
        raw = float(value)
        if raw >= 10000:
            return raw / 1000
        return raw

    @staticmethod
    def _parse_start_time(value) -> Optional[datetime]:
        """Garmin 시간 문자열을 datetime으로 변환."""
        if not value or not isinstance(value, str):
            return None
        normalized = value.replace("T", " ")
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                return datetime.strptime(normalized, fmt).replace(tzinfo=ZoneInfo(TIMEZONE))
            except ValueError:
                continue
        return None
