# 🏃‍♂️ Coach Gemini: Garmin Adaptive Training Sync

가민 커넥트(Garmin Connect)의 데이터를 분석하여 AI(Gemini)가 개인화된 7일 훈련 계획을 세워주고, 이를 가민과 구글 캘린더에 자동으로 동기화해주는 도구입니다.

## ✨ 주요 기능

*   **지능형 적응형 계획**: 어제의 실제 수면, 스트레스, HRV, 훈련 부하를 분석하여 오늘의 계획을 유동적으로 조정합니다.
*   **구체적인 대회 목표 설정**: 대회 날짜, 거리(풀, 하프, 10k 등), 목표 시간 또는 페이스를 설정하면 이에 맞춰 훈련 강도와 볼륨을 조절합니다.
*   **구글 캘린더 연동**: 생성된 상세 훈련 단계(Warmup, Run, Interval 등)와 코치 리포트를 구글 캘린더에 전용 캘린더("Coach Gemini")로 동기화합니다.
*   **완벽한 한국어 지원**: 모든 코칭 내용과 실행 로그가 한국어로 제공됩니다.
*   **도커(Docker) 기반 자동화**: 설정된 시간에 매일 아침 자동으로 실행되도록 구성할 수 있습니다.

## 🚀 시작하기

### 1. 패키지 설치

#### 방법 A: pip 설치 (권장)

```bash
pip install -e .
```

#### 방법 B: 개발 환경 설정

```bash
pip install -e ".[dev]"
```

### 2. 환경 설정

`.env` 파일을 생성하고 아래 정보를 입력합니다 (또는 `.env.example` 복사):

```ini
GARMIN_EMAIL=your_email@example.com
GARMIN_PASSWORD=your_password
GEMINI_API_KEY=your_gemini_api_key

# 선택 사항: 최대 심박수 (기본값: 220 - 나이)
MAX_HEART_RATE=185

# 대회 목표 (선택 사항)
RACE_DATE=2025-05-24
RACE_DISTANCE=Full
RACE_GOAL_TIME=3:59:59
# 또는 목표 페이스 설정 (예: 5분 40초/km)
# RACE_TARGET_PACE=5:40
```

### 3. 가민 인증 (최초 1회)

로컬 환경에서 가민 세션 토큰을 생성합니다:

```bash
python scripts/setup_garmin.py
```

### 4. 구글 캘린더 설정 (선택 사항)

1.  Google Cloud Console에서 Google Calendar API를 활성화합니다.
2.  `OAuth 클라이언트 ID`(데스크톱 앱)를 생성하고 JSON 파일을 다운로드하여 `./.google/credentials.json`으로 저장합니다.
3.  최초 실행 시 출력되는 링크를 통해 권한을 승인하면 `./.google/token_google.json`이 생성됩니다.

### 5. 실행 방법

#### 일회성 실행

```bash
coach-gemini
# 또는
python -m coach_gemini
```

#### 서비스 모드 (매일 자동 실행)

```bash
# 매일 오전 6시에 실행
coach-gemini --service --hour 6

# 근력 운동 포함
coach-gemini --service --hour 6 --include-strength
```

### 6. 도커 실행

```bash
docker-compose up -d
```

## 📂 프로젝트 구조

```
coach-gemini/
├── src/coach_gemini/         # 메인 패키지
│   ├── models/               # Pydantic 데이터 모델
│   ├── config/               # 설정 관리 (환경변수, 상수)
│   ├── clients/              # 외부 API 클라이언트
│   │   ├── garmin/          # Garmin Connect API
│   │   ├── gemini/          # Google Gemini AI
│   │   └── google_calendar/ # Google Calendar API
│   ├── core/                 # 핵심 비즈니스 로직
│   │   ├── container.py     # 의존성 주입 컨테이너
│   │   ├── orchestrator.py  # 훈련 계획 오케스트레이터
│   │   └── scheduler.py     # 스케줄링 서비스
│   ├── utils/                # 공통 유틸리티
│   └── __main__.py           # CLI 엔트리포인트
├── scripts/                  # 개발/운영 스크립트
│   └── setup_garmin.py      # 가민 계정 최초 인증 도구
├── tests/                    # 테스트 코드
├── pyproject.toml           # 프로젝트 설정 및 의존성
└── docker-compose.yml       # 도커 설정
```

---
오늘의 훈련도 파이팅입니다! 🏁
