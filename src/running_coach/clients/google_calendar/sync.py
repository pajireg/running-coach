"""캘린더 동기화 서비스"""

from datetime import date, datetime, timedelta, timezone
from typing import cast

from ...config.constants import (
    ACTIVITY_CALENDAR_NAME,
    CALENDAR_COLOR_ID,
    CALENDAR_NAME,
    TIMEZONE,
    WORKOUT_PREFIX,
)
from ...exceptions import CalendarSyncError
from ...models.training import TrainingPlan
from ...utils.logger import get_logger

logger = get_logger(__name__)


class CalendarSyncService:
    """캘린더 동기화 서비스"""

    def __init__(self, calendar_service):
        """
        Args:
            calendar_service: Google Calendar API 서비스 객체
        """
        self.service = calendar_service

    def sync(self, plan: TrainingPlan, calendar_name: str = CALENDAR_NAME) -> None:
        """훈련 계획을 구글 캘린더에 동기화

        Args:
            plan: TrainingPlan 모델
            calendar_name: 캘린더 이름
        """
        try:
            # 1. 전용 캘린더 찾기 또는 생성
            calendar_id = self._get_or_create_calendar(calendar_name)

            # 2. 기존 일정 정리
            self._cleanup_existing_events(calendar_id)

            # 3. 새로운 일정 등록
            self._create_events(calendar_id, plan)

            logger.info("구글 캘린더 동기화 완료!")

        except Exception as e:
            logger.error(f"구글 캘린더 동기화 중 에러 발생: {e}")
            raise CalendarSyncError(f"Failed to sync calendar: {e}") from e

    def sync_completed_activities(
        self,
        activities: list[dict[str, object]],
        as_of: date,
        calendar_name: str = ACTIVITY_CALENDAR_NAME,
        days_back: int | None = None,
    ) -> None:
        """실제 수행 활동을 별도 캘린더에 동기화."""
        try:
            calendar_id = self._get_or_create_calendar(calendar_name)
            sync_start_date, sync_end_date = self._activity_cleanup_range(
                activities=activities,
                as_of=as_of,
                days_back=days_back,
            )
            existing_events = self._list_events(
                calendar_id=calendar_id,
                start_date=sync_start_date,
                end_date=sync_end_date,
            )
            self._upsert_activity_events(
                calendar_id=calendar_id,
                activities=activities,
                existing_events=existing_events,
            )
            logger.info("실제 운동 기록 캘린더 동기화 완료!")
        except Exception as e:
            logger.error(f"실제 운동 기록 동기화 중 에러 발생: {e}")
            raise CalendarSyncError(f"Failed to sync completed activities: {e}") from e

    def _get_or_create_calendar(self, calendar_name: str) -> str:
        """캘린더 찾기 또는 생성

        Args:
            calendar_name: 캘린더 이름

        Returns:
            캘린더 ID
        """
        # 기존 캘린더 검색
        calendars = self.service.calendarList().list().execute().get("items", [])
        for cal in calendars:
            if cal.get("summary") == calendar_name:
                calendar_id = str(cal.get("id"))
                logger.info(f"기존 캘린더 발견: {calendar_name}")
                return calendar_id

        # 새 캘린더 생성
        logger.info(f"구글 캘린더 생성 중: {calendar_name}")
        new_cal = {"summary": calendar_name, "timeZone": "Asia/Seoul"}
        created_cal = self.service.calendars().insert(body=new_cal).execute()
        calendar_id = str(created_cal.get("id"))
        logger.info(f"캘린더 생성 완료: ID={calendar_id}")
        return calendar_id

    def _cleanup_existing_events(
        self,
        calendar_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> None:
        """기존 일정 정리 (어제부터 10일치)

        Args:
            calendar_id: 캘린더 ID
        """
        logger.info("기존 일정 정리 중...")

        # UTC 기준으로 범위 설정
        if start_date is None or end_date is None:
            now_utc = datetime.now(timezone.utc)
            start_cleanup = (now_utc - timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            end_cleanup = (now_utc + timedelta(days=10)).replace(
                hour=23, minute=59, second=59, microsecond=0
            )
        else:
            start_cleanup = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
            end_cleanup = datetime.combine(
                end_date, datetime.max.time().replace(microsecond=0), tzinfo=timezone.utc
            )

        time_min = start_cleanup.isoformat()
        time_max = end_cleanup.isoformat()

        events = (
            self.service.events()
            .list(calendarId=calendar_id, timeMin=time_min, timeMax=time_max)
            .execute()
            .get("items", [])
        )

        for event in events:
            self.service.events().delete(calendarId=calendar_id, eventId=event["id"]).execute()

        logger.info(f"{len(events)}개의 기존 일정 삭제됨")

    def _list_events(
        self,
        calendar_id: str,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, object]]:
        start_at = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
        end_at = datetime.combine(
            end_date, datetime.max.time().replace(microsecond=0), tzinfo=timezone.utc
        )
        items = (
            self.service.events()
            .list(
                calendarId=calendar_id,
                timeMin=start_at.isoformat(),
                timeMax=end_at.isoformat(),
            )
            .execute()
            .get("items", [])
        )
        return cast(list[dict[str, object]], items)

    def _create_events(self, calendar_id: str, plan: TrainingPlan) -> None:
        """새로운 일정 등록

        Args:
            calendar_id: 캘린더 ID
            plan: TrainingPlan 모델
        """
        logger.info("구글 캘린더에 일정 등록 중...")

        created_count = 0

        for daily_plan in plan.plan:
            workout = daily_plan.workout

            # 휴식일은 캘린더에도 등록하지 않음
            if daily_plan.session_type == "rest" or workout.is_rest:
                logger.debug(f"{daily_plan.date}: 휴식 - 건너뜀")
                continue

            display_title = workout.workout_name.replace(f"{WORKOUT_PREFIX}: ", "").strip()

            # 상세 설명 구축
            desc_lines = self._build_description(workout)

            event = {
                "summary": display_title,
                "description": "<br>".join(desc_lines),
                "start": {"date": daily_plan.date.isoformat()},
                "end": {"date": daily_plan.date.isoformat()},
                "colorId": CALENDAR_COLOR_ID,
            }

            self.service.events().insert(calendarId=calendar_id, body=event).execute()
            created_count += 1
            logger.debug(f"{daily_plan.date}: {display_title} 등록 완료")

        logger.info(f"{created_count}개의 일정 등록 완료")

    def _upsert_activity_events(
        self,
        calendar_id: str,
        activities: list[dict[str, object]],
        existing_events: list[dict[str, object]],
    ) -> None:
        """실제 수행 활동 이벤트 생성 또는 갱신."""
        logger.info("실제 운동 기록 이벤트 증분 동기화 중...")
        created_count = 0
        updated_count = 0
        existing_by_activity_key: dict[str, dict[str, object]] = {}
        for event in existing_events:
            extended = event.get("extendedProperties")
            if not isinstance(extended, dict):
                continue
            private = extended.get("private")
            if not isinstance(private, dict):
                continue
            provider = str(private.get("activityProvider") or "garmin")
            activity_id = private.get("providerActivityId") or private.get("garminActivityId")
            if activity_id:
                existing_by_activity_key[f"{provider}:{activity_id}"] = event

        for activity in activities:
            event = self._build_activity_event(activity)
            provider = str(activity.get("provider") or "garmin")
            activity_id = str(activity.get("providerActivityId") or "")
            existing_event = existing_by_activity_key.get(f"{provider}:{activity_id}")

            if existing_event and existing_event.get("id"):
                self.service.events().update(
                    calendarId=calendar_id,
                    eventId=existing_event["id"],
                    body=event,
                ).execute()
                updated_count += 1
            else:
                self.service.events().insert(calendarId=calendar_id, body=event).execute()
                created_count += 1

        logger.info(
            "%s개의 실제 운동 기록 생성, %s개의 기존 기록 갱신 완료",
            created_count,
            updated_count,
        )

    def _activity_cleanup_range(
        self,
        activities: list[dict[str, object]],
        as_of: date,
        days_back: int | None,
    ) -> tuple[date, date]:
        if activities:
            activity_dates = [
                date.fromisoformat(str(activity["activityDate"]))
                for activity in activities
                if activity.get("activityDate")
            ]
            if activity_dates:
                return min(activity_dates), max(activity_dates)

        if days_back is None:
            return as_of - timedelta(days=1), as_of

        return as_of - timedelta(days=days_back - 1), as_of

    def _build_activity_event(self, activity: dict[str, object]) -> dict[str, object]:
        sport_type = str(activity.get("sportType") or "workout")
        title = str(activity.get("title") or sport_type.title())
        distance_km = activity.get("distanceKm")
        if distance_km is not None:
            distance = self._float_or_none(distance_km)
            if distance is not None:
                title = f"{title} {distance:.2f}km"

        description_lines = [
            f"상태: {self._status_label(activity.get('executionStatus'))}",
            f"종목: {sport_type}",
            f"거리: {self._distance_label(activity.get('distanceKm'))}",
            f"시간: {self._duration_label(activity.get('durationSeconds'))}",
            f"평균 페이스: {activity.get('avgPace') or '-'}",
            f"평균 심박: {activity.get('avgHr') or '-'}",
            f"최대 심박: {activity.get('maxHr') or '-'}",
            f"고도 상승: {self._elevation_label(activity.get('elevationGainM'))}",
            "",
            str(activity.get("notes") or ""),
        ]
        planned_name = activity.get("plannedWorkoutName")
        if planned_name:
            description_lines.extend(
                [
                    "",
                    f"계획 워크아웃: {planned_name}",
                    f"계획 유형: {activity.get('plannedCategory') or '-'}",
                    f"실제 유형: {activity.get('actualCategory') or '-'}",
                    f"매칭 점수: {self._score_label(activity.get('targetMatchScore'))}",
                ]
            )

        started_at_raw = activity.get("startedAt")
        duration_seconds = self._int_or_none(activity.get("durationSeconds")) or 0
        if isinstance(started_at_raw, str):
            started_at = datetime.fromisoformat(started_at_raw)
            ended_at = started_at + timedelta(seconds=duration_seconds)
            start_payload: dict[str, object] = {
                "dateTime": started_at.isoformat(),
                "timeZone": TIMEZONE,
            }
            end_payload: dict[str, object] = {
                "dateTime": ended_at.isoformat(),
                "timeZone": TIMEZONE,
            }
        else:
            activity_date = str(activity.get("activityDate"))
            start_payload = {"date": activity_date}
            end_payload = {"date": activity_date}

        return {
            "summary": title,
            "description": "\n".join(line for line in description_lines if line is not None),
            "start": start_payload,
            "end": end_payload,
            "colorId": "10",
            "extendedProperties": {
                "private": {
                    "source": "running_coach_activity",
                    "activityDate": str(activity.get("activityDate")),
                    "activityProvider": str(activity.get("provider") or "garmin"),
                    "providerActivityId": str(activity.get("providerActivityId") or ""),
                }
            },
        }

    def _build_description(self, workout) -> list:
        """워크아웃 설명 생성

        Args:
            workout: Workout 모델

        Returns:
            설명 라인 목록
        """
        desc_lines = []

        # 1. 운동 단계 요약
        if workout.steps:
            desc_lines.append("🏃‍♂️ <b>훈련 단계:</b>")
            for i, step in enumerate(workout.steps):
                s_type = step.type
                duration = step.duration_value

                # 초 단위 시간을 분:초로 변환
                if duration >= 60:
                    dur_str = (
                        f"{duration // 60}분 {duration % 60}초"
                        if duration % 60
                        else f"{duration // 60}분"
                    )
                else:
                    dur_str = f"{duration}초"

                target = step.target_value
                target_str = f" (목표 페이스: {target})" if target and target != "0:00" else ""

                desc_lines.append(f"{i+1}. {s_type}: {dur_str}{target_str}")
            desc_lines.append("")  # 줄바꿈

        # 2. 한국어 설명 추가
        if workout.description:
            formatted_rationale = workout.description.replace("\n", "<br>")
            desc_lines.append(f"📝 <b>코치 리포트:</b><br>{formatted_rationale}")

        return desc_lines

    @staticmethod
    def _duration_label(value: object) -> str:
        seconds = CalendarSyncService._int_or_none(value)
        if not seconds:
            return "-"
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours}시간 {minutes}분 {secs}초"
        if minutes:
            return f"{minutes}분 {secs}초"
        return f"{secs}초"

    @staticmethod
    def _distance_label(value: object) -> str:
        distance = CalendarSyncService._float_or_none(value)
        if distance is None:
            return "-"
        return f"{distance:.2f}km"

    @staticmethod
    def _elevation_label(value: object) -> str:
        elevation = CalendarSyncService._float_or_none(value)
        if elevation is None:
            return "-"
        return f"{elevation:.0f}m"

    @staticmethod
    def _int_or_none(value: object) -> int | None:
        if value is None:
            return None
        try:
            if isinstance(value, (int, float, str)):
                return int(value)
            return None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _float_or_none(value: object) -> float | None:
        if value is None:
            return None
        try:
            if isinstance(value, (int, float, str)):
                return float(value)
            return None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _score_label(value: object) -> str:
        score = CalendarSyncService._float_or_none(value)
        if score is None:
            return "-"
        return f"{int(score * 100)}점"

    @staticmethod
    def _status_label(value: object) -> str:
        labels = {
            "completed_as_planned": "수행 완료",
            "completed_partial": "부분 수행",
            "completed_substituted": "대체 수행",
            "completed_unplanned": "비계획 수행",
        }
        return labels.get(str(value or ""), "실제 수행")
