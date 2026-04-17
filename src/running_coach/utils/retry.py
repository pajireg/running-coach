"""재시도 데코레이터"""

import logging

from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..exceptions import GeminiQuotaExceededError

logger = logging.getLogger(__name__)


def retry_on_quota_exceeded(max_attempts: int = 3):
    """Gemini 할당량 초과 시 재시도

    Args:
        max_attempts: 최대 시도 횟수

    Returns:
        tenacity retry 데코레이터
    """
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception_type(GeminiQuotaExceededError),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )


def retry_on_network_error(max_attempts: int = 3):
    """네트워크 에러 시 재시도

    Args:
        max_attempts: 최대 시도 횟수

    Returns:
        tenacity retry 데코레이터
    """
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )


def retry_on_any_error(max_attempts: int = 3, min_wait: int = 1, max_wait: int = 10):
    """모든 예외에 대해 재시도

    Args:
        max_attempts: 최대 시도 횟수
        min_wait: 최소 대기 시간 (초)
        max_wait: 최대 대기 시간 (초)

    Returns:
        tenacity retry 데코레이터
    """
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
        retry=retry_if_exception_type(Exception),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
