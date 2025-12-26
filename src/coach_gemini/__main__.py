"""CLI 엔트리포인트"""
import argparse
import time
from datetime import datetime
from .config.settings import get_settings
from .core.container import ServiceContainer
from .core.orchestrator import TrainingOrchestrator
from .core.scheduler import SchedulerService
from .utils.logger import get_logger

logger = get_logger(__name__)


def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(
        prog="coach-gemini",
        description="Coach Gemini: Advanced Adaptive Running Trainer"
    )
    parser.add_argument("--service", action="store_true", help="지속적인 서비스 모드로 실행")
    parser.add_argument("--hour", type=int, default=6, help="매일 실행될 시간 (0-23, 기본: 6)")
    parser.add_argument("--include-strength", action="store_true", help="계획에 근력 운동 포함 여부")
    args = parser.parse_args()

    # 시스템 시작 메시지
    print("--- Coach Gemini: Advanced Adaptive Trainer ---")
    now = datetime.now()
    tz_info = time.strftime("%Z")
    print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')} {tz_info}] 시스템 시작됨")

    # 설정 로드
    try:
        settings = get_settings()
        settings.service_mode = args.service
        settings.schedule_hour = args.hour
        settings.include_strength = args.include_strength
    except Exception as e:
        logger.error(f"설정 로드 실패: {e}")
        return

    # 컨테이너 생성
    container = ServiceContainer.create(settings)
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
