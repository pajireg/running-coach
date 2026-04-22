# Running Coach

[English](README.md) | 한국어

Running Coach는 Garmin Connect 데이터, Postgres 코칭 히스토리 DB, 그리고 규칙 기반 계획과 선택적 LLM-driven 계획을 지원하는 엔진 위에서 동작하는 상시 실행형 적응형 러닝 코치입니다.

이 프로젝트는 단순히 워크아웃을 생성하는 도구가 아닙니다. 선수의 훈련 이력을 누적하고, 현재 상태를 추정하고, 왜 그런 계획이 나왔는지 설명하며, Garmin과 Google Calendar까지 실제 실행 계층에 연결합니다.

## 핵심 기능

- Garmin 건강, 퍼포먼스, 활동, 캘린더 데이터 수집
- Postgres에 코칭 히스토리, 실행 이력, 의사결정 근거 저장
- 훈련 부하, 회복 상태, 레이스 목표, 가용 요일, 부상 상태, 주관 피드백을 바탕으로 7일 러닝 계획 생성
- 자전거, 등산, 근력운동 등 비러닝 활동 부하 반영
- 계획 대비 실제 수행을 해석
  - 일정 밀림
  - 자극 부족
  - 자극 과다
  - 비계획 세션
- Garmin Connect에 워크아웃 업로드 및 예약
- Garmin 워크아웃 제목은 `Recovery Run`, `Long Run`처럼 짧게 표시
- Google Calendar 두 개 동기화
  - `Running Coach`: 앞으로의 계획
  - `Workout`: 실제 완료한 운동 기록

## 시스템 기본 구조

Running Coach는 `LLM이 처음부터 끝까지 계획을 만드는 구조`가 아닙니다.

현재 구조는 다음과 같습니다.

1. Garmin과 사용자 입력이 원시 상태를 제공합니다.
2. Postgres가 정규화된 장기 히스토리를 저장합니다.
3. 활성 planner가 안전한 7일 계획을 만듭니다.
4. Safety rule이 Garmin과 캘린더 동기화 전에 계획을 검증하고 보정합니다.

핵심 원칙은 다음과 같습니다.

`코드는 안전 경계와 근거 정규화를 담당합니다. llm_driven 모드에서는 LLM이 그 hard bound 안에서 코칭 처방을 담당합니다.`

## 빠른 시작

### 1. 설치

```bash
pip install -e .
```

개발 도구까지 설치하려면:

```bash
pip install -e ".[dev]"
```

### 2. 환경 변수 설정

저장소 루트에 `.env` 파일을 생성합니다.

```ini
GARMIN_EMAIL=your_email@example.com
GARMIN_PASSWORD=your_password
GEMINI_API_KEY=your_gemini_api_key

# Optional
MAX_HEART_RATE=197
DATABASE_URL=postgresql://coach:coach@localhost:5432/running_coach
RACE_DATE=2026-05-24
RACE_DISTANCE=10K
RACE_GOAL_TIME=49:00
RACE_TARGET_PACE=4:54
```

### 3. Garmin 인증

한 번만 실행해서 Garmin 세션 토큰을 만듭니다.

```bash
python scripts/setup_garmin.py
```

토큰은 `./.garmin_tokens/`에 저장됩니다.

### 4. Google Calendar 인증

1. Google Cloud Console에서 Google Calendar API 활성화
2. OAuth Desktop App 클라이언트 생성
3. 내려받은 파일을 `./.google/credentials.json`으로 저장
4. 앱을 한 번 실행해서 OAuth 인증 완료
5. `./.google/token_google.json`이 자동 생성됨

### 5. 실행

1회 실행:

```bash
python -m running_coach
# 또는
running-coach
```

새 7일 계획과 Garmin 워크아웃 업로드를 강제로 다시 생성:

```bash
python -m running_coach run --mode plan
```

서비스 모드:

```bash
python -m running_coach run --service --times 05:00,17:00 --mode auto
```

서비스 실행 시각은 사용자별로 조정할 수 있습니다. `--times`는 하나 이상의 `HH:MM` 값을 받습니다.
현재 미래 계획을 새 7일 계획으로 교체하려면 `--mode plan`을 사용합니다.
일반 운영에서는 `--mode auto`를 사용합니다. `auto`는 먼저 Garmin/DB/Calendar 상태를
대조한 뒤 조건에 따라 skip, extend, replan 중 하나를 선택합니다.

## CLI 명령

- `python -m running_coach`
  - 데이터 수집, 계획 생성, Garmin 동기화, 캘린더 동기화 수행
- `python -m running_coach run --mode plan`
  - 7일 계획을 강제로 새로 생성하고, 저장된 Garmin workout ID 기준으로 기존 미래 워크아웃을 삭제한 뒤 non-rest 워크아웃을 다시 업로드하고 캘린더 동기화
- `python -m running_coach run --mode auto`
  - 1회 상태 대조를 수행하고 활성 계획이 없거나 오래됐거나 연장/재계획 트리거가 있을 때만 계획 생성
- `python -m running_coach run --service --times 05:00,17:00 --mode auto`
  - 설정 가능한 점검 시각으로 상시 실행하며 필요한 경우에만 재계획
- `python -m running_coach feedback ...`
  - 피로도, 근육통, 스트레스, 의욕, 수면 질 등 주관 피드백 저장
- `python -m running_coach availability ...`
  - 요일별 가능 여부, 선호 세션, 최대 운동 시간 저장
- `python -m running_coach goal ...`
  - 레이스 목표 저장
- `python -m running_coach block ...`
  - `base / build / peak / taper` 블록 정보 저장
- `python -m running_coach injury ...`
  - 활성 부상 상태와 심각도 저장

## Docker

```bash
docker-compose up -d --build
```

Docker 컨테이너 안에서 강제 재계획:

```bash
docker-compose exec -T garmin-coach python -m running_coach run --mode plan
```

Docker 컨테이너 안에서 1회 조건부 상태 대조:

```bash
docker-compose exec -T garmin-coach python -m running_coach run --mode auto
```

`python -m ...` 부분은 반드시 같은 셸 명령 한 줄에 있어야 합니다. `python`만 먼저
실행하면 CLI가 아니라 Python 프롬프트가 열립니다.

결정론적 legacy 플래너가 아니라 LLM-driven 플래너로 생성하려면 다음 값을 설정합니다.

```ini
COACH_PLANNER_MODE=llm_driven
```

주요 서비스:

- `postgres`
  - 코칭 히스토리 DB
- `garmin-coach`
  - 수집, 계획 생성, Garmin 동기화, Google Calendar 동기화

Docker에서 Google Calendar를 쓸 경우 `./.google/` 디렉터리가 컨테이너에 마운트되어 있어야 합니다.

## 품질 점검

```bash
pytest
ruff check src tests
black src tests
mypy src
```

## 저장소 구조

```text
src/running_coach/
  clients/          Garmin, Gemini, Google Calendar 연동
  config/           설정과 상수
  core/             오케스트레이터, 스케줄러, DI 컨테이너
  models/           Pydantic 모델
  storage/          Postgres 저장소와 코칭 히스토리 서비스
  utils/            공용 유틸리티
db/init/            Postgres 스키마 초기화
docs/               아키텍처 및 알고리즘 문서
scripts/            인증 및 운영 스크립트
tests/unit/         단위 테스트
```

## 문서

영문:

- [Coaching Architecture](docs/COACHING_ARCHITECTURE.md)
- [Coaching Algorithm](docs/COACHING_ALGORITHM.md)

한글:

- [Coaching Architecture (KO)](docs/COACHING_ARCHITECTURE.ko.md)
- [Coaching Algorithm (KO)](docs/COACHING_ALGORITHM.ko.md)

## 현재 코칭 신호

현재 코치 엔진은 다음 신호를 함께 사용합니다.

- 러닝 거리와 러닝 빈도
- 비러닝 부하
- training monotony / strain
- EWMA acute / chronic load
- Garmin 고유 부하 신호
  - training status
  - acute load
  - chronic load
  - ACWR
  - load balance
- 주관 회복 / 피로 피드백
- 레이스 목표와 훈련 블록
- 부상 제약
- 계획 대비 실제 수행 이력
- lap 기반 세션 품질 해석

## 현재 운영 원칙

- `Running Coach` 캘린더에는 미래 계획만 유지합니다.
- `Workout` 캘린더에는 실제 완료한 운동만 유지합니다.
- `Workout` 동기화는 최근 실제 운동 기준 증분 동기화입니다.
- 장기 과거 백필은 수동 작업으로 취급합니다.
- 실제 수행의 정본은 Garmin 활동 데이터입니다.
- Google Calendar는 표시와 리뷰 레이어이지, 정본 저장소가 아닙니다.

## 보안 주의사항

다음 파일과 디렉터리는 커밋하지 마십시오.

- `.env`
- `.garmin_tokens/`
- `.google/`

## 현재 상태

현재 시스템은 실제 Garmin 데이터, Postgres 저장, Garmin 워크아웃 업로드, Google Calendar 동기화까지 end-to-end로 동작합니다.

상세 의사결정 구조는 [Coaching Algorithm](docs/COACHING_ALGORITHM.md)에, 런타임 및 컴포넌트 구조는 [Coaching Architecture](docs/COACHING_ARCHITECTURE.md)에 정리되어 있습니다.
