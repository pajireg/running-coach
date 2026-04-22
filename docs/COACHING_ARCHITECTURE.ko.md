# Coaching Architecture

[English](COACHING_ARCHITECTURE.md) | 한국어

## 목표

Running Coach는 선수 히스토리를 계속 누적하고, 훈련 상태를 추정하고, 설명 가능한 계획을 만들고, 그 계획을 Garmin Connect와 Google Calendar 같은 실행 계층에 동기화하는 상시 실행형 코칭 백엔드로 설계되어 있습니다.

이 문서는 시스템의 런타임 구조, 주요 모듈의 책임, 그리고 데이터 수집, 상태 저장, 계획 생성, 표시 계층 사이의 경계를 설명합니다.

## 런타임 모델

기본 배포 모델은 Docker이며, 상시 실행을 전제로 합니다.

### 주요 런타임 서비스

- `postgres`
  - 코칭 히스토리와 상태를 저장하는 영속 DB
- `garmin-coach`
  - 수집, 계획 생성, Garmin 동기화, Google Calendar 동기화, 내부 스케줄링 담당

## 상위 흐름

1. 환경 설정과 선수 설정을 불러옵니다.
2. Garmin과 선택적 Google Calendar 인증을 수행합니다.
3. 건강, 퍼포먼스, 활동, 캘린더, 제약 맥락을 수집합니다.
4. 상태를 정규화해 Postgres에 저장합니다.
5. 계획 대비 실제 수행 링크를 다시 구성합니다.
6. 코칭 상태를 요약하고 `CoachingContext` 를 조립합니다.
7. `COACH_PLANNER_MODE` 에 따라 `legacy` 또는 `llm_driven` planner 로 분기합니다.
8. `llm_driven`: 프롬프트 렌더 → Gemini 호출 → JSON 파싱 → SafetyValidator 자동 보정.
9. `legacy`: 규칙 기반 skeleton, 결정론적 step, 결정론적 설명을 만듭니다.
10. 계획과 코치 의사결정 근거를 저장합니다.
11. Garmin 워크아웃 업로드(Rest Day skip) 및 Google Calendar 동기화를 수행합니다.

## 아키텍처 레이어

### 1. 수집 레이어

외부 시스템과 통신하며 원시 상태를 가져오는 계층입니다.

주요 모듈:

- `src/running_coach/clients/garmin/`
- `src/running_coach/clients/google_calendar/`

책임:

- Garmin 로그인과 토큰 관리
- 건강 / 퍼포먼스 데이터 수집
- 최근 활동과 lap 데이터 수집
- 예약 워크아웃 이력 수집
- Garmin 워크아웃 업로드 및 예약
- Google Calendar 이벤트 생성 및 업데이트

### 2. 정규화 및 저장 레이어

외부 원시 payload를 내부의 영속 상태로 바꾸는 계층입니다.

주요 모듈:

- `src/running_coach/storage/history_service.py`
- `src/running_coach/storage/database.py`

책임:

- athlete upsert
- 일일 메트릭 저장
- 활동 및 lap 저장
- 계획 워크아웃 저장
- 계획 대비 실제 수행 링크 구성
- 코칭 상태 요약
- 코치 의사결정 로그 저장

### 3. 계획 생성 레이어

저장된 상태를 안전하고 설명 가능한 주간 계획으로 바꾸는 계층입니다.

주요 모듈:

- `src/running_coach/coaching/context.py` — `CoachingContextBuilder` 가 점수·pace capability profile·14일 실행 이력·부상·피드백·가용성·훈련 배경을 `CoachingContext` dataclass 로 조립
- `src/running_coach/coaching/prompt.py` — `LLMPromptTemplate` 이 context 를 결정적(prompt cache 친화) 한국어 프롬프트로 렌더링 (threshold 노출 없음)
- `src/running_coach/coaching/safety/` — 15개 안전 룰 + 다중 패스 자동 보정을 수행하는 `SafetyValidator`
- `src/running_coach/coaching/planners/` — `Planner` 프로토콜, `LegacySkeletonPlanner`, `LLMDrivenPlanner`
- `src/running_coach/clients/gemini/planner.py` — 레거시 skeleton 계산 유틸

경로별 책임:

- `context.py`: history_service 출력을 타입 있는 context 로 변환 (chronic load, raw 14일 실행 행, staleness 태그된 피드백 등)
- `prompt.py`: 훈련 카탈로그(Interval, Threshold, Tempo Run, Fartlek, Long Run, Base Run, Recovery Run, Rest Day) 포함한 구조적 프롬프트 생성
- `safety/`: 하드 제약(계획 시작일=오늘, long_run 주 1회 상한, 연속 quality 금지, 부상 차단, ACWR 상한, 최소 1일 휴식, pace safety band, 워크아웃 이름 표준화 등) 자동 보정
- `planners/llm_driven.py`: `CoachingContext → prompt → Gemini → Pydantic → SafetyValidator` 파이프라인; 파싱/쿼터/미수렴 실패 시 `LegacySkeletonPlanner` fallback
- `clients/gemini/planner.py`: `LegacySkeletonPlanner` 가 재사용하는 skeleton 구성 유틸

### 4. 오케스트레이션 레이어

수집, 저장, 계획 생성, 업로드, 캘린더 동기화의 전체 흐름과 장애 경계를 관리하는 계층입니다.

주요 모듈:

- `src/running_coach/core/orchestrator.py`

책임:

- 수집, 저장, 계획 생성, 업로드, 캘린더 동기화 순서 제어
- 부분 실패가 전체 계획 히스토리를 깨지 않도록 보호
- 설명 가능한 상태 스냅샷과 의사결정 근거 저장

## DB의 역할

DB는 애플리케이션의 정본 상태 저장소입니다.

### 핵심 테이블

- `athletes`
  - 선수 식별자와 프로필
- `daily_metrics`
  - 일일 회복, 훈련 상태, 부하 스냅샷
- `activities`
  - 정규화된 실제 활동
- `activity_laps`
  - 세션 품질 해석을 위한 lap / split 상세
- `planned_workouts`
  - 미래 계획 히스토리
- `workout_executions`
  - 계획 대비 실제 수행 링크와 실행 해석
- `subjective_feedback`
  - 피로도, 근육통, 스트레스, 의욕, 수면 질 입력
- `injury_status`
  - 활성 부상 제약과 심각도
- `availability_rules`
  - 요일별 제약과 선호
- `training_blocks`
  - base / build / peak / taper 블록 정보
- `race_goals`
  - 레이스 목표 데이터
- `coach_decisions`
  - 설명 가능한 계획 스냅샷과 의사결정 근거

## 외부 시스템 경계

### Garmin Connect

역할:

- 기기 기반 건강, 퍼포먼스, 활동 데이터의 원천
- 예약 워크아웃의 업로드 대상

중요한 경계:

- Garmin은 센서와 실행 데이터의 원천이지, 내부 정본 상태 저장소는 아닙니다.
- 예약 워크아웃은 가능하면 DB에 저장된 Garmin workout ID로 추적하므로, 사용자에게 보이는 워크아웃 제목에는 `Running Coach:` prefix를 붙이지 않아도 됩니다.

### Google Calendar

역할:

- 사용자에게 보여주는 표시 계층

현재 사용하는 캘린더:

- `Running Coach`
  - 미래 계획 세션
- `Workout`
  - 실제 완료한 세션만

중요한 경계:

- Google Calendar는 정본이 아닙니다.
- 캘린더 이벤트는 DB 상태를 투영한 결과물입니다.

### Postgres

역할:

- 코칭 히스토리의 정본 상태 저장소
- 계획 메모리
- 실행 메모리
- 의사결정 근거 저장소

## 계획 생성 경계: Rules vs LLM

경계선은 `COACH_PLANNER_MODE` 에 따라 다릅니다.

### `llm_driven` 모드 (새 기본 지향)

**알고리즘이 담당하는 것 (hard bounds)**:

- readiness / fatigue / injury 점수화 (`history_service`)
- LT / PR / race target 기반 pace capability profile 과 safety band 계산
- 재계획 트리거 감지 (`summarize_plan_freshness`)
- `SafetyValidator` 로 강제되는 안전 룰:
  - 계획 시작일은 반드시 오늘
  - 활성 부상 severity ≥ 6 → quality 제거, 볼륨 × 0.65
  - 활성 부상 severity 3–5 → 인터벌 제거, 볼륨 × 0.85
  - 주간 long_run ≤ 1회
  - 사용자 선호 long_run 가용 날짜가 있으면 long_run은 그 날짜 중 하나에 배치
  - 연속된 두 날 hard session 금지
  - long run 다음 날 quality 금지
  - quality 세션 사이 최소 48시간
  - 주간 hard ≤ 2회
  - availability / max duration / 주간 최소 1일 휴식 준수
  - 주간 km / chronic-weekly ≤ 1.5 (ACWR 상한) — 구조적 + duration 스케일링
  - step pace 는 해당 pace safety band 안에 있어야 함
  - non-rest 인 날은 step 유효 (각 step ≥ 60s)
  - 세션 타입 + step 구조에 기반한 워크아웃 이름 표준화

**LLM이 담당하는 것 (판단)**:

- 7일 세션 타입 배치
- 주간 볼륨 목표
- 일자별 plannedMinutes
- step 구조 (warmup/run/interval/recovery/cooldown 구성)
- safety band 안에서의 구체 target pace
- phase 해석 (base / build / peak / taper)
- 한국어 근거 및 위험 인지 (riskAcknowledgements)
- 선수 상태에 따른 훈련 다양성 선택 (Interval vs Threshold vs Tempo vs Fartlek)

LLM 출력이 안전 룰을 위반하면 validator 가 자동 보정하고 로그를 남깁니다. 보정이 수렴하지 못하면 `LegacySkeletonPlanner` 로 fallback 합니다.

### `legacy` 모드 (fallback, `llm_driven` 검증 완료 전까지 기본)

Legacy 경로는 `planner._build_weekly_skeleton` 에서 규칙 기반 skeleton 을 만들고, `StepTemplateEngine` 과 `DescriptionRenderer` 로 workout step 과 한국어 설명을 Gemini 호출 없이 채웁니다.

이 분리는 시스템을 더 설명 가능하게 만들고, 위험한 계획 드리프트를 줄입니다.

## 스케줄러와 운영 시각

서비스 실행 시각은 설정 가능합니다. 사용자는 Docker의 `COACH_SCHEDULE_TIMES` 또는 CLI의 `--times`로 `05:00,17:00`처럼 하루 여러 번의 점검 시각을 지정할 수 있습니다.

이유:

- 이른 아침 운동 전에 계획이 준비되어 있어야 합니다.
- 전날 완료한 운동을 이 시점에 반영할 수 있습니다.
- Garmin에서 아침에 워크아웃을 확인하기 전에 계획을 갱신할 수 있습니다.
- 실제 사용자는 출근 전, 퇴근 후, 또는 불규칙하게 운동할 수 있으므로 스케줄러가 하나의 고정 루틴을 가정하면 안 됩니다.

운영 원칙:

- 서비스 모드는 기본적으로 `auto` 모드로 실행합니다.
- 각 실행은 먼저 Garmin, DB, Calendar 상태를 대조합니다.
- 활성 계획이 없거나, 마지막 계획 이후 새 활동이 생겼거나, 마지막 계획 이후 회복 지표가 크게 나빠졌거나, 핵심 세션을 수행하지 않았거나, base 볼륨 누락이 누적된 경우에만 LLM을 호출합니다.
- recovery run 1회 미수행은 추가 휴식으로 보고 그 자체만으로는 재계획하지 않습니다.
- 미수행 판단은 현재 `as_of` 날짜 이전만 대상으로 하므로, 오후 점검에서 당일 저녁 운동을 아직 안 했다는 이유만으로 미수행 처리하지 않습니다.
- 실제 운동 캘린더 동기화는 증분 방식입니다.
- 대규모 과거 백필은 수동 작업으로 처리합니다.

## 실패와 일관성 원칙

시스템은 부분 실패가 나도 완전히 망가지지 않도록 설계되어 있습니다.

### 현재 원칙

- 계획 생성 실패가 기존 미래 워크아웃을 지우면 안 됩니다.
- 캘린더 동기화 실패가 DB 히스토리를 지우면 안 됩니다.
- 업로드나 캘린더 문제는 수집과 상태 저장과 분리되어야 합니다.
- 외부 동기화가 일부 실패해도 정규화된 DB row는 남아 있어야 합니다.

## 현재 강점

- 실제 Garmin 실행 루프가 end-to-end로 동작합니다.
- 코치 의사결정이 저장되고 설명 가능합니다.
- 계획 대비 실제 수행 해석이 다음 주 계획에 다시 반영됩니다.
- Google Calendar가 미래 계획과 실제 운동을 명확히 분리합니다.
- 비러닝 부하와 Garmin 고유 부하를 함께 사용합니다.
- `legacy` 모드는 결정론적 center pace로, `llm_driven` 모드는 safety band 안에서 LLM이 선택한 pace로 워크아웃 target을 개인화합니다.

## 현재 한계

- 선수별 개인화는 더 긴 히스토리가 쌓일수록 좋아집니다.
- 세션 품질 해석은 아직 더 정교화할 여지가 있습니다.
- 제품 수준 UI는 아직 거의 없습니다.
- 운영 가시성과 리포팅은 아직 가볍습니다.

## 추천 다음 단계

1. `coach_decisions` 위에 리포트와 대시보드를 추가합니다.
2. lap, pace, HR drift 기반 세션 품질 해석을 계속 고도화합니다.
3. 더 긴 실행 히스토리 기반 선수별 적응성을 강화합니다.
4. 재시도, 모니터링, 동기화 상태 가시성을 강화합니다.
