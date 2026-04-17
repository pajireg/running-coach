"""CLI 엔트리포인트"""

import argparse
import time
from datetime import datetime

from .config.constants import APP_CLI_NAME, APP_NAME, DEFAULT_SCHEDULE_HOUR
from .config.settings import get_settings
from .core.container import ServiceContainer
from .core.orchestrator import TrainingOrchestrator
from .core.scheduler import SchedulerService
from .models.feedback import SubjectiveFeedback
from .utils.logger import get_logger

logger = get_logger(__name__)


def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(
        prog=APP_CLI_NAME,
        description=f"{APP_NAME}: Advanced Adaptive Running Trainer",
    )
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="1회 실행 또는 서비스 모드")
    run_parser.add_argument("--service", action="store_true", help="지속적인 서비스 모드로 실행")
    run_parser.add_argument(
        "--hour",
        type=int,
        default=DEFAULT_SCHEDULE_HOUR,
        help=f"매일 실행될 시간 (0-23, 기본: {DEFAULT_SCHEDULE_HOUR})",
    )
    run_parser.add_argument(
        "--include-strength", action="store_true", help="계획에 근력 운동 포함 여부"
    )

    feedback_parser = subparsers.add_parser("feedback", help="주관 피드백 저장")
    feedback_parser.add_argument("--date", dest="feedback_date", required=True, help="YYYY-MM-DD")
    feedback_parser.add_argument("--fatigue", type=int, help="피로도 1-10")
    feedback_parser.add_argument("--soreness", type=int, help="근육통 1-10")
    feedback_parser.add_argument("--stress", type=int, help="스트레스 1-10")
    feedback_parser.add_argument("--motivation", type=int, help="의욕 1-10")
    feedback_parser.add_argument("--sleep-quality", type=int, help="체감 수면 질 1-10")
    feedback_parser.add_argument("--pain-notes", help="통증 메모")
    feedback_parser.add_argument("--notes", help="자유 메모")

    availability_parser = subparsers.add_parser("availability", help="요일별 훈련 가능 조건 저장")
    availability_parser.add_argument(
        "--weekday", type=int, required=True, help="0=월요일 ... 6=일요일"
    )
    availability_parser.add_argument(
        "--is-available",
        choices=["true", "false"],
        default="true",
        help="해당 요일 훈련 가능 여부",
    )
    availability_parser.add_argument("--max-minutes", type=int, help="최대 훈련 시간(분)")
    availability_parser.add_argument("--preferred-session-type", help="선호 세션 타입")

    goal_parser = subparsers.add_parser("goal", help="레이스 목표 저장")
    goal_parser.add_argument("--name", required=True, help="목표 이름")
    goal_parser.add_argument("--race-date", help="YYYY-MM-DD")
    goal_parser.add_argument("--distance", help="예: 10K, Half, Full")
    goal_parser.add_argument("--goal-time", help="예: 49:00 또는 3:45:00")
    goal_parser.add_argument("--target-pace", help="예: 4:54")
    goal_parser.add_argument("--priority", type=int, default=1, help="우선순위")

    block_parser = subparsers.add_parser("block", help="훈련 블록 저장")
    block_parser.add_argument("--phase", required=True, help="예: base, build, peak, taper")
    block_parser.add_argument("--starts-on", required=True, help="YYYY-MM-DD")
    block_parser.add_argument("--ends-on", required=True, help="YYYY-MM-DD")
    block_parser.add_argument("--focus", help="블록 핵심 목표")
    block_parser.add_argument("--weekly-volume-km", type=float, help="주간 목표 거리")

    injury_parser = subparsers.add_parser("injury", help="부상 상태 저장")
    injury_parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    injury_parser.add_argument("--area", required=True, help="통증/부상 부위")
    injury_parser.add_argument("--severity", type=int, required=True, help="0-10")
    injury_parser.add_argument("--notes", help="부상 메모")
    injury_parser.add_argument(
        "--is-active", choices=["true", "false"], default="true", help="현재 활성 여부"
    )

    args = parser.parse_args()
    if args.command is None:
        args.command = "run"
        args.service = False
        args.hour = DEFAULT_SCHEDULE_HOUR
        args.include_strength = False

    # 시스템 시작 메시지
    print(f"--- {APP_NAME}: Advanced Adaptive Trainer ---")
    now = datetime.now()
    tz_info = time.strftime("%Z")
    print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')} {tz_info}] 시스템 시작됨")

    # 설정 로드
    try:
        settings = get_settings()
    except Exception as e:
        logger.error(f"설정 로드 실패: {e}")
        return

    # 컨테이너 생성
    container = ServiceContainer.create(settings)

    if args.command == "feedback":
        try:
            container.history_service.db.ping()
            container.history_service.ensure_athlete(
                garmin_email=settings.garmin_email,
                max_heart_rate=settings.max_heart_rate,
            )
            feedback = SubjectiveFeedback(
                feedbackDate=args.feedback_date,
                fatigueScore=args.fatigue,
                sorenessScore=args.soreness,
                stressScore=args.stress,
                motivationScore=args.motivation,
                sleepQualityScore=args.sleep_quality,
                painNotes=args.pain_notes,
                notes=args.notes,
            )
            container.history_service.record_subjective_feedback(feedback)
            logger.info(f"주관 피드백 저장 완료: {feedback.feedback_date}")
        except Exception as e:
            logger.error(f"주관 피드백 저장 실패: {e}")
        return

    if args.command == "availability":
        try:
            container.history_service.db.ping()
            container.history_service.ensure_athlete(
                garmin_email=settings.garmin_email,
                max_heart_rate=settings.max_heart_rate,
            )
            container.history_service.upsert_availability_rule(
                weekday=args.weekday,
                is_available=args.is_available == "true",
                max_duration_minutes=args.max_minutes,
                preferred_session_type=args.preferred_session_type,
            )
            logger.info(f"가용 요일 저장 완료: weekday={args.weekday}")
        except Exception as e:
            logger.error(f"가용 요일 저장 실패: {e}")
        return

    if args.command == "goal":
        try:
            container.history_service.db.ping()
            container.history_service.ensure_athlete(
                garmin_email=settings.garmin_email,
                max_heart_rate=settings.max_heart_rate,
            )
            container.history_service.upsert_race_goal(
                goal_name=args.name,
                race_date=datetime.fromisoformat(args.race_date).date() if args.race_date else None,
                distance=args.distance,
                goal_time=args.goal_time,
                target_pace=args.target_pace,
                priority=args.priority,
            )
            logger.info(f"레이스 목표 저장 완료: {args.name}")
        except Exception as e:
            logger.error(f"레이스 목표 저장 실패: {e}")
        return

    if args.command == "block":
        try:
            container.history_service.db.ping()
            container.history_service.ensure_athlete(
                garmin_email=settings.garmin_email,
                max_heart_rate=settings.max_heart_rate,
            )
            container.history_service.upsert_training_block(
                phase=args.phase,
                starts_on=datetime.fromisoformat(args.starts_on).date(),
                ends_on=datetime.fromisoformat(args.ends_on).date(),
                focus=args.focus,
                weekly_volume_target_km=args.weekly_volume_km,
            )
            logger.info(f"훈련 블록 저장 완료: {args.phase}")
        except Exception as e:
            logger.error(f"훈련 블록 저장 실패: {e}")
        return

    if args.command == "injury":
        try:
            container.history_service.db.ping()
            container.history_service.ensure_athlete(
                garmin_email=settings.garmin_email,
                max_heart_rate=settings.max_heart_rate,
            )
            container.history_service.upsert_injury_status(
                status_date=datetime.fromisoformat(args.date).date(),
                injury_area=args.area,
                severity=args.severity,
                notes=args.notes,
                is_active=args.is_active == "true",
            )
            logger.info(f"부상 상태 저장 완료: {args.area}")
        except Exception as e:
            logger.error(f"부상 상태 저장 실패: {e}")
        return

    settings.service_mode = args.service
    settings.schedule_hour = args.hour
    settings.include_strength = args.include_strength
    orchestrator = TrainingOrchestrator(container)

    # 실행 모드 분기
    if args.service:
        # 서비스 모드
        scheduler = SchedulerService(orchestrator, settings)
        scheduler.run()
    else:
        # 1회 실행 모드
        orchestrator.run_once()


if __name__ == "__main__":
    main()
