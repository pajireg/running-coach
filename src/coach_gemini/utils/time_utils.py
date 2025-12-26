"""시간 변환 유틸리티"""
import re
from typing import Optional


def format_seconds(seconds: Optional[int]) -> str:
    """초를 '시간 분' 형식으로 변환

    Args:
        seconds: 초 단위 시간

    Returns:
        "H시간 M분" 또는 "M분" 형식 문자열

    Examples:
        >>> format_seconds(3665)
        "1시간 1분"
        >>> format_seconds(120)
        "2분"
        >>> format_seconds(None)
        "0분"
    """
    if not seconds:
        return "0분"

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60

    if hours > 0:
        return f"{hours}시간 {minutes}분"
    else:
        return f"{minutes}분"


def pace_to_ms(pace_str: str, margin: int = 0) -> float:
    """페이스를 m/s (초당 미터)로 변환

    Args:
        pace_str: "MM:SS" 형식의 페이스 (예: "5:40")
        margin: 여유 초 (양수: 느리게, 음수: 빠르게)

    Returns:
        m/s (초당 미터) 값

    Examples:
        >>> pace_to_ms("5:00")  # 5분/km
        3.33
        >>> pace_to_ms("5:00", margin=15)  # 5:15/km (느리게)
        3.17
        >>> pace_to_ms("5:00", margin=-15)  # 4:45/km (빠르게)
        3.51
    """
    # MM:SS 형식 파싱
    match = re.match(r'^(\d+):(\d{2})$', pace_str)
    if not match:
        raise ValueError(f"Invalid pace format: {pace_str}. Expected MM:SS")

    minutes = int(match.group(1))
    seconds = int(match.group(2))

    # 총 초로 변환 + margin 적용
    total_seconds = (minutes * 60 + seconds) + margin

    # m/s 계산 (1km = 1000m)
    if total_seconds <= 0:
        raise ValueError(f"Invalid total seconds: {total_seconds}")

    return 1000.0 / total_seconds


def ms_to_pace(ms: float) -> str:
    """m/s (초당 미터)를 페이스(MM:SS/km)로 변환

    Args:
        ms: m/s (초당 미터) 값

    Returns:
        "MM:SS" 형식의 페이스

    Examples:
        >>> ms_to_pace(3.33)
        "5:00"
    """
    if ms <= 0:
        raise ValueError(f"Invalid m/s value: {ms}")

    # 1km를 달리는데 걸리는 시간 (초)
    total_seconds = 1000.0 / ms

    minutes = int(total_seconds // 60)
    seconds = int(total_seconds % 60)

    return f"{minutes}:{seconds:02d}"


def format_duration_from_seconds(seconds: int) -> str:
    """초를 HH:MM:SS 형식으로 변환

    Args:
        seconds: 초 단위 시간

    Returns:
        "HH:MM:SS" 또는 "MM:SS" 형식 문자열

    Examples:
        >>> format_duration_from_seconds(3665)
        "1:01:05"
        >>> format_duration_from_seconds(125)
        "2:05"
    """
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes}:{secs:02d}"
