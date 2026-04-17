# Running Coach

Garmin Connect 데이터를 기반으로 7일 러닝 계획을 생성하고, Garmin 워크아웃과 Google Calendar까지 동기화하는 AI 러닝 코치입니다. 현재 구조는 단순 계획 생성기를 넘어서, Postgres에 훈련 히스토리와 코치 판단 근거를 저장하는 장기 코칭 백엔드로 확장되어 있습니다.

## 주요 기능

- Garmin 건강, 퍼포먼스, 활동 데이터를 수집합니다.
- 최근 훈련량, 주관 피드백, 목표 레이스, 가용 요일을 반영해 7일 계획을 만듭니다.
- 생성한 계획을 Garmin 워크아웃으로 업로드하고 캘린더에 예약합니다.
- Postgres에 `daily_metrics`, `activities`, `planned_workouts`, `workout_executions`, `coach_decisions`를 저장합니다.
- Google Calendar에 두 개의 전용 캘린더를 동기화합니다.
  - `Running Coach`: 앞으로의 계획
  - `Workout`: 최근 실제 운동 기록과 계획 대비 상태

## 빠른 시작

### 1. 설치

```bash
pip install -e .
```

개발 도구까지 설치하려면:

```bash
pip install -e ".[dev]"
```

### 2. 환경 변수

프로젝트 루트에 `.env`를 두고 최소한 아래 값을 채우십시오.

```ini
GARMIN_EMAIL=your_email@example.com
GARMIN_PASSWORD=your_password
GEMINI_API_KEY=your_gemini_api_key

# 선택 사항
MAX_HEART_RATE=197
DATABASE_URL=postgresql://coach:coach@localhost:5432/running_coach
RACE_DATE=2026-05-24
RACE_DISTANCE=10K
RACE_GOAL_TIME=49:00
RACE_TARGET_PACE=4:54
```

### 3. Garmin 인증

최초 1회 Garmin 세션 토큰을 생성합니다.

```bash
python scripts/setup_garmin.py
```

토큰은 `./.garmin_tokens/`에 저장됩니다.

### 4. Google Calendar 인증

1. Google Cloud Console에서 Google Calendar API를 활성화합니다.
2. OAuth Desktop App 클라이언트를 생성합니다.
3. 내려받은 JSON을 `./.google/credentials.json`에 둡니다.
4. 앱을 한 번 실행해 OAuth 승인을 완료하면 `./.google/token_google.json`이 생성됩니다.

### 5. 실행

일회성 실행:

```bash
python -m running_coach
# 또는
running-coach
```

서비스 모드:

```bash
python -m running_coach run --service --hour 5
```

기본 스케줄 시간은 오전 5시입니다.

## CLI 명령

- `python -m running_coach`
  - 하루치 수집, 계획 생성, Garmin/Calendar 동기화
- `python -m running_coach feedback ...`
  - 피로도, 근육통, 수면 체감 등 주관 피드백 저장
- `python -m running_coach availability ...`
  - 요일별 훈련 가능 여부와 최대 시간 저장
- `python -m running_coach goal ...`
  - 목표 레이스 저장
- `python -m running_coach block ...`
  - `base/build/peak/taper` 블록 저장
- `python -m running_coach injury ...`
  - 부상 상태 저장

## Docker 실행

```bash
docker-compose up -d --build
```

서비스 구성:

- `postgres`: 코칭 히스토리 저장소
- `garmin-coach`: 수집, 계획 생성, Garmin 업로드, Google Calendar 동기화

Google Calendar를 Docker에서도 쓰려면 `./.google/` 디렉터리가 있어야 합니다.

## 품질 검사

```bash
pytest
ruff check src tests
black src tests
mypy src
```

## 프로젝트 구조

```text
src/running_coach/
  clients/          Garmin, Gemini, Google Calendar 연동
  config/           설정, 상수
  core/             orchestrator, scheduler, container
  models/           Pydantic 모델
  storage/          Postgres 저장 및 코칭 히스토리 서비스
  utils/            공통 유틸리티
db/init/            Postgres 초기 스키마
docs/               운영 및 아키텍처 문서
scripts/            인증/운영 스크립트
tests/unit/         단위 테스트
```

## 보안 주의사항

다음 파일과 디렉터리는 커밋하지 마십시오.

- `.env`
- `.garmin_tokens/`
- `.google/`

## 현재 동작 요약

- 계획 생성은 규칙 기반 skeleton + LLM 보정 구조입니다.
- 실제 운동 기록은 Garmin 활동 기준으로 DB에 저장됩니다.
- `Workout` 캘린더에는 실제 수행만 기록하고, 설명에 계획 대비 상태를 표시합니다.
- `미수행`은 캘린더가 아니라 DB에서만 관리합니다.
