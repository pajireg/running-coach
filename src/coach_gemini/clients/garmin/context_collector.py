"""활동 컨텍스트 데이터 수집기"""
from typing import List
from datetime import date as DateType, timedelta, datetime
from ...models.context import ActivityContext, Activity, ScheduleItem, MonthlyStats
from ...utils.logger import get_logger

logger = get_logger(__name__)


class ContextDataCollector:
    """활동 컨텍스트 데이터 수집기"""

    def __init__(self, garmin_connection):
        """
        Args:
            garmin_connection: garminconnect.Garmin 인스턴스
        """
        self.garmin = garmin_connection

    def collect(self, target_date: DateType) -> ActivityContext:
        """컨텍스트 수집 (통합)

        Args:
            target_date: 기준 날짜

        Returns:
            ActivityContext 모델
        """
        logger.info("활동 컨텍스트 수집 중...")

        return ActivityContext(
            yesterday_actual=self._get_yesterday_activities(target_date),
            current_schedule=self._get_30day_schedule(target_date),
            yearly_trend=self._get_yearly_trend()
        )

    def _get_yesterday_activities(self, target_date: DateType) -> List[Activity]:
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
                activities.append(Activity(
                    name=act.get("activityName"),
                    type=act.get("activityType", {}).get("typeKey") if isinstance(act.get("activityType"), dict) else None,
                    distance=act.get("distance"),
                    duration=act.get("duration"),
                    calories=act.get("calories")
                ))

            logger.info(f"어제 활동 내역 수집 완료: {len(activities)} 개의 활동")
            return activities

        except Exception as e:
            logger.warning(f"어제 활동 내역 수집 실패: {e}")
            return []

    def _get_30day_schedule(self, target_date: DateType) -> List[ScheduleItem]:
        """최근 30일 일정 (라인 302-369)

        Args:
            target_date: 기준 날짜

        Returns:
            최근 30일 일정 목록
        """
        try:
            thirty_days_ago = target_date - timedelta(days=30)

            # 조회할 월 리스트 생성 (이번 달, 지난달)
            months_to_fetch = []
            curr = target_date
            months_to_fetch.append((curr.year, curr.month))

            # 지난달 계산
            first_of_curr = curr.replace(day=1)
            last_month_end = first_of_curr - timedelta(days=1)
            months_to_fetch.append((last_month_end.year, last_month_end.month))

            all_items = []
            for y, m in months_to_fetch:
                url = f"/calendar-service/year/{y}/month/{m-1}"  # 0-indexed month
                try:
                    resp = self.garmin.garth.get("connectapi", url, api=True)
                    cal_data = resp.json()
                    all_items.extend(cal_data.get("calendarItems", []))
                except:
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

                item_date = DateType.fromisoformat(item_date_str)

                # 최근 30일 이내인지 확인
                if thirty_days_ago <= item_date <= target_date:
                    item_type = item.get("itemType")
                    if item_type in ["workout", "activity"]:
                        summary = ""
                        if item_type == "activity":
                            raw_dist = item.get('activeSplitSummaryDistance') or item.get('distance', 0)
                            dist_km = round(float(raw_dist) / 1000, 2) if raw_dist else 0

                            raw_dur = item.get('elapsedDuration') or (item.get('duration', 0) / 1000)
                            h = int(raw_dur // 3600)
                            m = int((raw_dur % 3600) // 60)
                            s = int(raw_dur % 60)
                            dur_str = f"{h}h {m}m {s}s" if h > 0 else f"{m}m {s}s"

                            avg_hr = item.get('averageHR', 'N/A')
                            summary = f"({dist_km}km, {dur_str}, HR: {avg_hr})"

                        schedule_items.append(ScheduleItem(
                            date=item_date,
                            title=item.get("title") or "",
                            type=item_type,
                            details=summary
                        ))
                        seen_ids.add(item_id)

            # 날짜순 정렬
            schedule_items.sort(key=lambda x: x.date)

            logger.info(f"최근 30일 훈련 및 활동 수집 완료: {len(schedule_items)} 개의 항목")
            return schedule_items

        except Exception as e:
            logger.warning(f"최근 일정 수집 실패: {e}")
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

            limit_date = datetime.now() - timedelta(days=365)

            for act in all_activities:
                start_time_str = act.get("startTimeLocal")
                if not start_time_str:
                    continue

                start_time = datetime.fromisoformat(start_time_str)

                if start_time < limit_date:
                    break  # 1년 이전 데이터면 조기 종료

                key = (start_time.year, start_time.month)
                if key not in yearly_stats:
                    yearly_stats[key] = {"dist": 0, "count": 0}

                yearly_stats[key]["dist"] += (act.get("distance", 0) / 1000)
                yearly_stats[key]["count"] += 1

            # 보기 좋게 정렬
            sorted_keys = sorted(yearly_stats.keys(), reverse=True)
            monthly_stats = []

            for y, m in sorted_keys:
                s = yearly_stats[(y, m)]
                monthly_stats.append(MonthlyStats(
                    year=y,
                    month=m,
                    distance_km=s['dist'],
                    activity_count=s['count']
                ))

            logger.info(f"연간 훈련 요약 수집 완료: {len(monthly_stats)} 개월 데이터")
            return monthly_stats

        except Exception as e:
            logger.warning(f"연간 요약 수집 실패: {e}")
            return []
