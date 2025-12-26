"""로깅 설정"""
import logging
import sys
from pathlib import Path
from typing import Optional

# 로그 레벨 매핑
LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL
}

# 로거 인스턴스 캐시
_loggers = {}


def get_logger(name: str, level: str = "INFO", log_to_file: bool = True) -> logging.Logger:
    """구조화된 로거 생성

    Args:
        name: 로거 이름 (일반적으로 __name__)
        level: 로그 레벨 ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
        log_to_file: 파일 핸들러 추가 여부

    Returns:
        설정된 Logger 인스턴스
    """
    # 캐시된 로거 반환
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)
    logger.setLevel(LOG_LEVELS.get(level, logging.INFO))

    # 이미 핸들러가 있으면 중복 방지
    if logger.handlers:
        return logger

    # 포맷터 생성
    formatter = logging.Formatter(
        fmt='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 콘솔 핸들러
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 파일 핸들러
    if log_to_file:
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "coach_gemini.log", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # 캐시에 저장
    _loggers[name] = logger

    return logger


def set_global_log_level(level: str) -> None:
    """전역 로그 레벨 변경

    Args:
        level: 로그 레벨 ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
    """
    log_level = LOG_LEVELS.get(level, logging.INFO)
    for logger in _loggers.values():
        logger.setLevel(log_level)
