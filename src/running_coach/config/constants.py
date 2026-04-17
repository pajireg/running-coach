"""상수 정의"""

from pathlib import Path

# 앱 식별자
APP_NAME = "Running Coach"
APP_CLI_NAME = "running-coach"
APP_PACKAGE_NAME = "running_coach"
WORKOUT_PREFIX = "Running Coach"
LEGACY_WORKOUT_PREFIXES = ("Coach Gemini",)
SUPPORTED_WORKOUT_PREFIXES = (WORKOUT_PREFIX, *LEGACY_WORKOUT_PREFIXES)
CALENDAR_NAME = "Running Coach"
ACTIVITY_CALENDAR_NAME = "Workout"
WORKOUT_SOURCE = "running_coach"
DEFAULT_DB_NAME = "running_coach"

# 디렉토리 경로
BASE_DIR = Path(__file__).parent.parent.parent.parent
GARMIN_TOKEN_DIR = BASE_DIR / ".garmin_tokens"
GOOGLE_DIR = BASE_DIR / ".google"
GOOGLE_CREDENTIALS_FILE = GOOGLE_DIR / "credentials.json"
GOOGLE_TOKEN_FILE = GOOGLE_DIR / "token_google.json"
LOGS_DIR = BASE_DIR / "logs"

# Google Calendar
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar",
]

# Garmin 개인 기록 타입 매핑
PR_TYPE_MAP = {
    1: "1K",
    2: "MILE",
    3: "5K",
    4: "10K",
    5: "HALF_MARATHON",
    6: "MARATHON",
    7: "LONG_RUN",
}

# 워크아웃 타입 매핑
STEP_TYPE_MAP = {
    "Warmup": "warmup",
    "Cooldown": "cooldown",
    "Recovery": "recovery",
    "Rest": "rest",
    "Interval": "interval",
    "Run": "run",
}

# Gemini 모델
GEMINI_MODEL = "gemini-3-flash-preview"

# 페이스 마진 (초)
DEFAULT_PACE_MARGIN = 15

# 캘린더 색상
CALENDAR_COLOR_ID = "1"  # 라벤더

# 스케줄 설정
DEFAULT_SCHEDULE_HOUR = 5

# 타임존
TIMEZONE = "Asia/Seoul"
