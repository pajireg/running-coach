"""캘린더 동기화 서비스"""
from typing import Optional
from datetime import timedelta, datetime, timezone
from ...models.training import TrainingPlan
from ...config.constants import CALENDAR_COLOR_ID
from ...utils.logger import get_logger
from ...exceptions import CalendarSyncError

logger = get_logger(__name__)


class CalendarSyncService:
    """캘린더 동기화 서비스"""

    def __init__(self, calendar_service):
        """
        Args:
            calendar_service: Google Calendar API 서비스 객체
        """
        self.service = calendar_service

    def sync(self, plan: TrainingPlan, calendar_name: str = "Coach Gemini") -> None:
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

    def _get_or_create_calendar(self, calendar_name: str) -> str:
        """캘린더 찾기 또는 생성

        Args:
            calendar_name: 캘린더 이름

        Returns:
            캘린더 ID
        """
        # 기존 캘린더 검색
        calendars = self.service.calendarList().list().execute().get('items', [])
        for cal in calendars:
            if cal.get('summary') == calendar_name:
                calendar_id = cal.get('id')
                logger.info(f"기존 캘린더 발견: {calendar_name}")
                return calendar_id

        # 새 캘린더 생성
        logger.info(f"구글 캘린더 생성 중: {calendar_name}")
        new_cal = {
            'summary': calendar_name,
            'timeZone': 'Asia/Seoul'
        }
        created_cal = self.service.calendars().insert(body=new_cal).execute()
        calendar_id = created_cal.get('id')
        logger.info(f"캘린더 생성 완료: ID={calendar_id}")
        return calendar_id

    def _cleanup_existing_events(self, calendar_id: str) -> None:
        """기존 일정 정리 (어제부터 10일치)

        Args:
            calendar_id: 캘린더 ID
        """
        logger.info("기존 일정 정리 중...")

        # UTC 기준으로 범위 설정
        now_utc = datetime.now(timezone.utc)
        start_cleanup = (now_utc - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_cleanup = (now_utc + timedelta(days=10)).replace(hour=23, minute=59, second=59, microsecond=0)

        time_min = start_cleanup.isoformat()
        time_max = end_cleanup.isoformat()

        events = self.service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max
        ).execute().get('items', [])

        for event in events:
            self.service.events().delete(calendarId=calendar_id, eventId=event['id']).execute()

        logger.info(f"{len(events)}개의 기존 일정 삭제됨")

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

            # 휴식 워크아웃은 건너뛰기
            if workout.is_rest:
                logger.debug(f"{daily_plan.date}: 휴식 - 건너뜀")
                continue

            # 제목에서 "Coach Gemini: " 접두어 제거
            display_title = workout.workout_name.replace("Coach Gemini: ", "").strip()

            # 상세 설명 구축
            desc_lines = self._build_description(workout)

            event = {
                'summary': display_title,
                'description': "<br>".join(desc_lines),
                'start': {'date': daily_plan.date.isoformat()},
                'end': {'date': daily_plan.date.isoformat()},
                'colorId': CALENDAR_COLOR_ID
            }

            self.service.events().insert(calendarId=calendar_id, body=event).execute()
            created_count += 1
            logger.debug(f"{daily_plan.date}: {display_title} 등록 완료")

        logger.info(f"{created_count}개의 일정 등록 완료")

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
                    dur_str = f"{duration // 60}분 {duration % 60}초" if duration % 60 else f"{duration // 60}분"
                else:
                    dur_str = f"{duration}초"

                target = step.target_value
                target_str = f" (목표 페이스: {target})" if target and target != "0:00" else ""

                desc_lines.append(f"{i+1}. {s_type}: {dur_str}{target_str}")
            desc_lines.append("")  # 줄바꿈

        # 2. 한국어 설명 추가
        if workout.description:
            formatted_rationale = workout.description.replace('\n', '<br>')
            desc_lines.append(f"📝 <b>코치 리포트:</b><br>{formatted_rationale}")

        return desc_lines
