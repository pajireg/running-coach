"""Garmin 전용 유틸리티"""

from typing import Any, Dict, Optional


def parse_sleep_quality(qualifier_key: Optional[str]) -> str:
    """수면 품질 키를 한국어로 변환

    Args:
        qualifier_key: Garmin API의 qualifierKey (예: "GOOD", "FAIR", "POOR")

    Returns:
        한국어 품질 설명
    """
    quality_map = {"EXCELLENT": "매우 좋음", "GOOD": "좋음", "FAIR": "보통", "POOR": "나쁨"}
    if qualifier_key is None:
        return "알 수 없음"
    return quality_map.get(qualifier_key, qualifier_key)


def parse_training_status(status_key: Optional[str]) -> str:
    """훈련 상태 키를 한국어로 변환

    Args:
        status_key: Garmin API의 훈련 상태 키

    Returns:
        한국어 상태 설명
    """
    status_map = {
        "PRODUCTIVE": "생산적",
        "MAINTAINING": "유지 중",
        "RECOVERY": "회복 중",
        "UNPRODUCTIVE": "비생산적",
        "DETRAINING": "저하 중",
        "OVERREACHING": "과도 훈련",
    }
    if status_key is None:
        return "N/A"
    return status_map.get(status_key, status_key)


def safe_get(data: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    """중첩된 딕셔너리에서 안전하게 값 가져오기

    Args:
        data: 딕셔너리
        *keys: 중첩된 키들
        default: 기본값

    Returns:
        값 또는 기본값

    Example:
        >>> data = {"a": {"b": {"c": 123}}}
        >>> safe_get(data, "a", "b", "c")
        123
        >>> safe_get(data, "a", "x", "y", default=0)
        0
    """
    result: Any = data
    for key in keys:
        if not isinstance(result, dict):
            return default
        result = result.get(key)
        if result is None:
            return default
    return result
