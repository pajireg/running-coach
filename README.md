# 🏃‍♂️ Coach Gemini: Garmin Adaptive Training Sync

가민 커넥트(Garmin Connect)의 데이터를 분석하여 AI(Gemini)가 개인화된 7일 훈련 계획을 세워주고, 이를 가민과 구글 캘린더에 자동으로 동기화해주는 도구입니다.

## ✨ 주요 기능

*   **지능형 적응형 계획**: 어제의 실제 수면, 스트레스, HRV, 훈련 부하를 분석하여 오늘의 계획을 유동적으로 조정합니다.
*   **구체적인 대회 목표 설정**: 대회 날짜, 거리(풀, 하프, 10k 등), 목표 시간 또는 페이스를 설정하면 이에 맞춰 훈련 강도와 볼륨을 조절합니다.
*   **구글 캘린더 연동**: 생성된 상세 훈련 단계(Warmup, Run, Interval 등)와 코치 리포트를 구글 캘린더에 전용 캘린더("Coach Gemini")로 동기화합니다.
*   **완벽한 한국어 지원**: 모든 코칭 내용과 실행 로그가 한국어로 제공됩니다.
*   **도커(Docker) 기반 자동화**: 설정된 시간에 매일 아침 자동으로 실행되도록 구성할 수 있습니다.

## 🚀 시작하기

### 1. 환경 설정

`.env` 파일을 생성하고 아래 정보를 입력합니다 (또는 `.env.example` 복사):

```ini
GARMIN_EMAIL=your_email@example.com
GARMIN_PASSWORD=your_password
GEMINI_API_KEY=your_gemini_api_key

# 대회 목표 (선택 사항)
RACE_DATE=2025-05-24
RACE_DISTANCE=Full
RACE_GOAL_TIME=3:59:59
```

### 2. 가민 인증 (최초 1회)

로컬 환경에서 가민 세션 토큰을 생성합니다:

```bash
python setup_garmin.py
```

### 3. 구글 캘린더 설정 (선택 사항)

1.  Google Cloud Console에서 Google Calendar API를 활성화합니다.
2.  `OAuth 클라이언트 ID`(데스크톱 앱)를 생성하고 JSON 파일을 다운로드하여 `credentials.json`으로 저장합니다.
3.  최초 실행 시 출력되는 링크를 통해 권한을 승인하면 `token_google.json`이 생성됩니다.

### 4. 도커 실행

```bash
docker-compose up -d
```

## 📂 프로젝트 구조

*   `garmin_coach.py`: 메인 엔진 (데이터 수집, Gemini 연동, 가민/구글 동기화)
*   `setup_garmin.py`: 가민 계정 최초 인증 도구
*   `patch_garth.py`: 최신 파이썬 환경을 위한 가민 라이브러리 패치
*   `docker-compose.yml`: 매일 자동 실행을 위한 도커 설정

## 🛡️ 보안 주의사항

*   `.env`, `.garmin_tokens/`, `credentials.json`, `token_google.json` 파일은 절대 외부나 공개된 깃 저장소에 공유하지 마십시오. `.gitignore`에 이미 포함되어 있습니다.

---
오늘의 훈련도 파이팅입니다! 🏁
