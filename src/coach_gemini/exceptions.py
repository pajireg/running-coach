"""커스텀 예외 클래스"""


class CoachGeminiError(Exception):
    """기본 예외 클래스"""
    pass


# Garmin 관련 예외
class GarminError(CoachGeminiError):
    """Garmin API 기본 에러"""
    pass


class GarminAuthenticationError(GarminError):
    """인증 실패"""
    pass


class GarminDataError(GarminError):
    """데이터 수집 실패"""
    pass


class GarminWorkoutError(GarminError):
    """워크아웃 생성/업로드 실패"""
    pass


# Gemini 관련 예외
class GeminiError(CoachGeminiError):
    """Gemini API 기본 에러"""
    pass


class GeminiQuotaExceededError(GeminiError):
    """할당량 초과 (429)"""
    pass


class GeminiResponseParseError(GeminiError):
    """응답 파싱 실패"""
    pass


# Google Calendar 관련 예외
class CalendarError(CoachGeminiError):
    """Google Calendar 기본 에러"""
    pass


class CalendarAuthError(CalendarError):
    """인증 실패"""
    pass


class CalendarSyncError(CalendarError):
    """동기화 실패"""
    pass


# 설정 관련 예외
class ConfigurationError(CoachGeminiError):
    """설정 오류"""
    pass
