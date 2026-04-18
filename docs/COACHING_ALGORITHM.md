# Coaching Algorithm

## Purpose
`Running Coach`는 단순히 LLM에게 7일 계획을 맡기는 구조가 아닙니다. 현재 구현은 다음 4단계를 결합한 하이브리드 코치 엔진입니다.

1. Garmin과 사용자 입력에서 데이터를 수집합니다.
2. DB에 장기 히스토리를 쌓고 상태를 추정합니다.
3. 규칙 엔진이 안전한 주간 skeleton을 먼저 만듭니다.
4. LLM은 그 skeleton 안에서 세션 설명과 구체 내용을 보정합니다.

핵심 원칙은 `안전 제약과 구조는 코드가 담당하고, LLM은 해석과 설명을 담당한다`입니다.

## Data Inputs
현재 코치 엔진은 아래 데이터를 사용합니다.

### Garmin daily metrics
- `body_battery`
- `hrv`
- `sleep_score`
- `resting_hr`
- `training_status`

### Garmin performance metrics
- PR
- VO2max
- lactate threshold pace / HR
- max HR

### Garmin activity history
- 러닝 거리, 시간, 심박, 고도
- lap / split
- training effect label
- 최근 7일/30일 러닝량
- 최근 7일 비러닝 운동 시간

### User constraints
- `availability_rules`
- `race_goals`
- `training_blocks`
- `subjective_feedback`
- `injury_status`

### Execution history
- `planned_workouts`
- `activities`
- `workout_executions`

## System Flow
실행 흐름은 대략 아래와 같습니다.

1. Garmin에서 건강, 퍼포먼스, 활동, 캘린더 데이터를 수집합니다.
2. `activities`, `daily_metrics`, `planned_workouts` 등에 정규화해서 저장합니다.
3. 실제 활동과 과거 계획을 연결해 `workout_executions`를 계산합니다.
4. 최근 6주, 12개월, 평생 배경과 최근 42일 load를 요약합니다.
5. `readiness`, `fatigue`, `injury_risk`를 계산합니다.
6. 규칙 엔진이 7일 skeleton을 생성합니다.
7. LLM이 skeleton을 유지한 채 description과 steps를 만듭니다.
8. 결과를 Garmin, Google Calendar, Postgres에 동기화합니다.

관련 구현 위치:
- `src/running_coach/storage/history_service.py`
- `src/running_coach/clients/gemini/planner.py`
- `src/running_coach/core/orchestrator.py`

## Load Model
이 시스템은 단순히 최근 7일 거리만 보지 않습니다. 러닝과 크로스트레이닝을 함께 반영한 `load_units`를 만듭니다.

현재 일일 load 정의:
- running load: 그날 러닝 거리 km 합계
- cross-training load: 비러닝 운동 시간(초) / 600
- total daily load: `running_km + non_running_seconds / 600`

즉 자전거, 등산, 근력운동도 러닝 계획에 영향을 줍니다. 다만 러닝과 비러닝을 같은 척도로 완벽히 환산하는 것이 아니라, `추가 부하 신호`로 사용하는 보수적 모델입니다.

### Derived signals
최근 7일, 28일, 42일 데이터를 바탕으로 다음 값을 계산합니다.

- `last7dDistanceKm`
- `last28dDistanceKm`
- `last7dRunCount`
- `last7dCrossTrainingMinutes`
- `avgDailyLoad`
- `peakDailyLoad`
- `activeDays`
- `trainingMonotony = avg_daily_load / sd_daily_load`
- `trainingStrain = total_load * training_monotony`
- `acuteEwmaLoad` (7일 EWMA)
- `chronicEwmaLoad` (28일 EWMA)
- `ewmaLoadRatio = acute / chronic`

여기서 ACWR류 지표는 `단독 의사결정 기준`이 아니라, monotony / strain / recovery와 함께 보는 보조 신호입니다.

## Recovery Model
회복 상태는 Garmin과 사용자 피드백을 함께 봅니다.

사용 신호:
- `body_battery`
- `sleep_score`
- `hrv`
- `subjective fatigue`
- `soreness`
- `stress`
- `sleep_quality`
- `motivation`

원칙:
- 객관 지표와 주관 지표를 함께 봅니다.
- Garmin 수치가 좋아도 사용자가 통증과 피로를 강하게 보고하면 보수적으로 해석합니다.
- 반대로 최근 부하가 높아도 회복 신호가 안정적이면 readiness를 지나치게 깎지 않습니다.

## Adherence and Planned-vs-Actual
전문 코치화에서 중요한 부분은 `무엇을 했는가`뿐 아니라 `계획과 어떻게 달랐는가`입니다.

현재 시스템은 활동마다 가장 가까운 계획 세션을 찾습니다.

매칭 기준:
- 날짜 근접성: `-2일 ~ +3일`
- planned vs actual category
- duration 유사성
- 이미 매칭된 계획인지 여부

세션 카테고리:
- `recovery`
- `base`
- `long_run`
- `quality`
- `unplanned`

매칭 후 아래 값을 저장합니다.
- `completion_ratio`
- `target_match_score`
- `executionStatus`
- `deviationReason`
- `coachInterpretation`

### executionStatus
- `completed_as_planned`
- `completed_partial`
- `completed_substituted`
- `completed_unplanned`

### deviationReason
- `as_planned`
- `schedule_shift`
- `reduced_stimulus`
- `excessive_stimulus`
- `execution_variation`
- `unplanned_session`

예:
- Recovery Run 계획인데 실제로 quality 성격으로 수행하면 `excessive_stimulus`
- Quality 계획인데 base 성격으로 수행하면 `reduced_stimulus`
- 같은 성격이지만 하루 밀리면 `schedule_shift`

이 정보는 단순 로그가 아니라 다음 주 계획에도 반영됩니다.

## State Estimation
현재 엔진은 3개 점수를 계산합니다.

### readinessScore
높을수록 훈련을 소화할 준비가 된 상태입니다.

올리는 신호:
- 충분한 chronic load
- 안정적인 EWMA ratio
- 좋은 adherence
- 높은 body battery
- 좋은 sleep / HRV
- 높은 motivation

내리는 신호:
- 높은 최근 7일 거리
- 과한 비러닝 부하
- 높은 monotony / strain
- 높은 unplanned / skipped workload
- 높은 subjective fatigue / soreness

### fatigueScore
높을수록 최근 피로가 큰 상태입니다.

올리는 신호:
- 높은 최근 7일 load
- 높은 cross-training minutes
- 급격한 overload ratio
- 높은 monotony / strain
- 높은 acute EWMA
- fatigue / stress / soreness 주관 점수

내리는 신호:
- 높은 body battery
- 좋은 sleep score

### injuryRiskScore
높을수록 부상 리스크가 높은 상태입니다.

올리는 신호:
- overload ratio 상승
- monotony / strain 상승
- acute EWMA 상승
- soreness / fatigue / pain notes
- active injury severity

내리는 신호:
- 충분한 chronic load
- 안정적인 recovery 지표

이 점수들은 의학적 진단이 아니라 `planning signal`입니다. 즉 의료 판단이 아니라 훈련 계획의 보수성 수준을 조절하는 데 사용됩니다.

## Rule-Based Weekly Skeleton
LLM 이전에 규칙 엔진이 먼저 7일 구조를 만듭니다.

결정하는 것:
- run day 수
- quality 세션 수
- long run 배치
- recovery / rest 위치
- target minutes
- availability와 preferred day 반영

현재 규칙 예시:
- readiness가 낮거나 fatigue / injury가 높으면 quality 제거
- active injury severity가 높으면 quality 제거, volume 감산
- 최근 비계획 고강도나 장거리 세션이 있으면 recovery 쪽으로 기울임
- long run은 토/일과 사용자 선호 요일을 우선 반영
- quality는 mid-week와 사용자 선호 요일을 우선 반영
- 불가 요일은 rest로 강제
- high non-running load가 있으면 run day와 quality를 줄임

즉 LLM은 `요일 구조를 창조`하지 않습니다. 안전성과 periodization의 바깥 테두리는 코드가 먼저 고정합니다.

## LLM Role
LLM은 아래 역할만 합니다.

- skeleton을 유지한 채 세션 description 작성
- 세션 step 구성
- race context를 반영한 wording 보정
- 한국어 코치 설명 생성

LLM이 할 수 없는 것:
- skeleton 날짜 변경
- session type 변경
- workout name 임의 변경
- 과도한 볼륨 증가

출력 후에도 정규화 단계를 다시 거칩니다.
- invalid pace 제거
- zero-duration step 제거
- 잘못된 date / workout name 교정
- skeleton과 크게 어긋난 step은 fallback step으로 대체

## Why This Design
이 구조를 택한 이유는 세 가지입니다.

1. LLM 단독 계획은 일관성과 안전성이 흔들릴 수 있습니다.
2. 단순 규칙 엔진만으로는 개인의 최근 반응과 맥락 해석이 부족합니다.
3. 실제 코치는 `데이터 해석 + 안전 제약 + 설명`을 함께 합니다.

따라서 현재 시스템은:
- 규칙 엔진으로 안전성과 일관성을 확보하고
- DB 히스토리로 장기 맥락을 유지하고
- LLM으로 설명력과 유연성을 보강합니다.

## Scientific References
이 시스템은 특정 논문 하나를 그대로 구현한 것이 아니라, 아래 문헌의 원칙을 실무형으로 조합한 것입니다.

### Training load, monotony, EWMA, ACWR caution
- Rico-González et al. *Acute:chronic workload ratio and training monotony variations over the season in professional soccer: A systematic review*  
  https://journals.sagepub.com/doi/10.1177/17543371231194283
- Afonso et al. *A Novel Approach to Training Monotony and Acute-Chronic Workload Index*  
  https://pubmed.ncbi.nlm.nih.gov/34136806/

해석:
- ACWR는 단독 injury predictor로 과신하지 않습니다.
- monotony, strain, EWMA, recovery를 함께 봅니다.

### Planned vs actual mismatch
- Gomes et al. *Internal Training Load Perceived by Athletes and Planned by Coaches: A Systematic Review and Meta-Analysis*  
  https://pubmed.ncbi.nlm.nih.gov/35244801/
- Frontiers exploratory study on planned vs actual external load  
  https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2026.1768705/full

해석:
- 코치가 의도한 자극과 실제 자극은 자주 어긋납니다.
- 따라서 완료 여부만이 아니라 `어떤 방향으로 어긋났는지`를 저장해야 합니다.

### Sleep and recovery
- Hamlin et al. *The Effect of Sleep Quality and Quantity on Athlete's Health and Perceived Training Quality*  
  https://pubmed.ncbi.nlm.nih.gov/34568820/
- Boardman et al. *The impact of sleep loss on performance monitoring and error-monitoring*  
  https://pubmed.ncbi.nlm.nih.gov/33894599/

해석:
- 수면과 회복 상태는 훈련 수행과 건강에 직접적 영향을 줍니다.
- 따라서 sleep / HRV / body battery는 readiness에 포함됩니다.

### Endurance periodization
- Mølmen et al. *Block periodization of endurance training - a systematic review and meta-analysis*  
  https://pubmed.ncbi.nlm.nih.gov/31802956/
- Wilmore et al. *Cross-training and periodization in running*  
  https://pubmed.ncbi.nlm.nih.gov/24572330/

해석:
- 레이스 목표, 블록, 크로스트레이닝은 주간 구조 설계에 반영해야 합니다.
- 특히 running-specific plan이라도 cross-training load를 무시하면 안 됩니다.

## Current Limits
현재 알고리즘은 이미 실동작하지만, 아직 개선 여지가 있습니다.

- Garmin native acute/chronic load를 자체 load 모델과 더 정교하게 통합 가능
- 세션 강도 판정은 현재 category 기반이라 향후 pace/HR drift 기반으로 더 정밀화 가능
- 개인별 반응 모델은 아직 rule-heavy이며, 장기 히스토리가 더 쌓이면 personalization을 강화할 수 있음
- 의료적 부상 판단 엔진은 아님

## Summary
현재 `Running Coach`의 코치 알고리즘은 다음 한 문장으로 요약할 수 있습니다.

`Garmin + 사용자 입력 + DB 히스토리로 상태를 추정하고, 규칙 엔진이 안전한 주간 구조를 만든 뒤, LLM이 그 구조 안에서 세션 설명과 디테일을 보정하는 하이브리드 코치 시스템`

즉 이 프로젝트의 목표는 `그럴듯한 플랜 생성기`가 아니라, `설명 가능하고 누적 학습되는 실행형 러닝 코치`입니다.
