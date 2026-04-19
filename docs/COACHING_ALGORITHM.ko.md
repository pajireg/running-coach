# Coaching Algorithm

[English](COACHING_ALGORITHM.md) | 한국어

## 목적

Running Coach는 LLM이 처음부터 끝까지 계획을 만들어내는 시스템이 아닙니다. 현재 코치 엔진은 선수 히스토리 저장, 규칙 기반 안전 제어, 제한된 범위의 LLM 보정을 결합한 하이브리드 구조입니다.

핵심 원칙은 다음과 같습니다.

`안전성과 구조는 코드가 담당하고, 해석과 설명은 LLM이 제한된 범위에서 담당합니다.`

이 문서는 코치 엔진이 무엇을 보고, 어떤 방식으로 신호를 만들고, 왜 지금 구조를 선택했는지를 설명합니다.

## 코칭 레이어

현재 시스템은 네 개의 레이어로 동작합니다.

1. **데이터 수집**
   Garmin과 사용자 입력으로 건강, 퍼포먼스, 활동, 제약 정보를 받습니다.
2. **상태 저장과 정규화**
   Postgres에 원시 데이터가 아니라 정규화된 장기 히스토리를 저장합니다.
3. **규칙 기반 계획 생성**
   회복, 부하, 실행 이력, 제약을 바탕으로 주간 skeleton을 생성합니다.
4. **LLM 보정**
   정해진 제약 안에서 세션 설명과 워크아웃 step을 채웁니다.

## 입력 데이터

### Garmin 일일 메트릭

- `body_battery`
- `hrv`
- `sleep_score`
- `resting_hr`
- `training_status`
- `load_balance_phrase`
- `acute_load`
- `chronic_load`
- `acwr`

### Garmin 퍼포먼스 메트릭

- PR
- VO2max
- 젖산역치 페이스와 심박
- 최대심박수

### Garmin 활동 이력

- 거리, 시간, 심박, 고도
- 활동 타입
- lap / split
- 가능한 경우 training effect 라벨
- 최근 7일 / 30일 러닝 부하
- 최근 비러닝 활동 시간

### 사용자 제약 정보

- `availability_rules`
- `race_goals`
- `training_blocks`
- `subjective_feedback`
- `injury_status`

### 실행 이력

- `planned_workouts`
- `activities`
- `workout_executions`

## 전체 흐름

1. Garmin 건강, 퍼포먼스, 활동, 예약 워크아웃 맥락을 수집합니다.
2. 데이터를 정규화해서 Postgres에 저장합니다.
3. 계획 대비 실제 수행 링크를 다시 구성합니다.
4. 최근 부하, 장기 배경, 현재 코칭 상태를 요약합니다.
5. `readinessScore`, `fatigueScore`, `injuryRiskScore`를 계산합니다.
6. 규칙 기반 7일 skeleton을 생성합니다.
7. LLM이 skeleton을 깨지 않는 범위에서 설명과 워크아웃 세부를 채웁니다.
8. 계획과 의사결정 근거를 저장합니다.
9. Garmin 워크아웃과 Google Calendar를 동기화합니다.

`auto` 서비스 모드에서는 활성 계획이 충분히 최신이면 6-9단계를 건너뜁니다. 계획 범위가 비어 있거나, 마지막 계획 이후 새 Garmin 활동이 생겼거나, 이전 날짜의 계획된 운동이 의미 있게 수행되지 않은 경우 재계획합니다.

주요 구현 위치:

- `src/running_coach/storage/history_service.py`
- `src/running_coach/clients/gemini/planner.py`
- `src/running_coach/core/orchestrator.py`

## 부하 모델

엔진은 최근 러닝 거리만 보지 않습니다. 러닝과 비러닝 활동을 함께 보는 혼합 부하 모델을 사용합니다.

### 일일 부하 정의

- 러닝 부하: 그날의 총 러닝 거리 km
- 비러닝 부하: 그날의 비러닝 운동 시간(초) / `600`
- 총 일일 부하:
  - `running_km + non_running_seconds / 600`

이 방식은 의도적으로 보수적입니다. 자전거, 등산, 근력운동을 러닝 등가거리처럼 과하게 환산하지 않고, 추가 부하 신호로만 반영합니다.

### 파생 부하 지표

현재 계산하는 값:

- `last7dDistanceKm`
- `last28dDistanceKm`
- `last7dRunCount`
- `last7dCrossTrainingMinutes`
- `avgDailyLoad`
- `peakDailyLoad`
- `activeDays`
- `trainingMonotony`
- `trainingStrain`
- `acuteEwmaLoad`
- `chronicEwmaLoad`
- `ewmaLoadRatio`

### Garmin 고유 부하와의 하이브리드

DB 기반 부하 모델만 쓰지 않고, Garmin 고유 부하 신호도 보정용으로 함께 사용합니다.

- `trainingStatus`
- `loadBalancePhrase`
- `garminAcuteLoad`
- `garminChronicLoad`
- `garminAcwr`

해석 원칙:

- 정규화된 장기 히스토리는 DB 기반 모델이 중심입니다.
- Garmin 부하 신호는 보정 레이어입니다.
- Garmin 값이 좋아도 부상, 통증, 강한 주관 피로를 덮어쓰지는 않습니다.

## 회복 모델

회복 상태는 기기 데이터와 주관 피드백을 함께 사용해 추정합니다.

### 회복 입력

- `body_battery`
- `sleep_score`
- `hrv`
- `training_status`
- `load_balance_phrase`
- 주관 피로도
- 근육통
- 스트레스
- 수면 체감
- 의욕
- 활성 부상 심각도

### 회복 해석 원칙

- 객관 신호와 주관 신호를 함께 봅니다.
- 기기 수치가 좋아도 통증이나 근육통이 크면 그대로 강하게 가지 않습니다.
- 최근 부하가 높아도 회복 신호가 안정적이면 무조건 나쁘게 보지 않습니다.
- 부상 심각도는 강한 보수화 신호로 취급합니다.

## 계획 대비 실제 수행 해석

전문 코치 수준에서는 “운동을 했는가?”보다 “계획과 어떻게 달랐는가?”가 더 중요합니다.

### 매칭 로직

각 실제 활동은 가장 그럴듯한 계획 세션과 매칭됩니다.

기준:

- 날짜 근접성: `-2일 ~ +3일`
- 계획 카테고리와 실제 카테고리 유사성
- 시간 유사성
- 이미 매칭된 계획인지 여부

### 세션 카테고리

- `recovery`
- `base`
- `long_run`
- `quality`
- `unplanned`

### 저장되는 실행 필드

- `completion_ratio`
- `target_match_score`
- `executionStatus`
- `deviationReason`
- `coachInterpretation`
- `executionQuality`

### 실행 매칭점수

`target_match_score`는 계획 대비 실제 수행 일치도 점수입니다. 운동 능력 점수나 레이스 예측 점수, 또는 “잘 뛰었는지”를 평가하는 성과 점수가 아닙니다.

이 점수가 답하는 질문은 다음에 가깝습니다.

- “선수가 계획한 세션 의도를 실제로 수행했는가?”

예를 들어 `0.98`은 실제 운동이 계획과 매우 가까웠다는 뜻입니다. long run이라면 보통 다음을 의미합니다.

- 계획 카테고리가 `long_run`
- 실제 카테고리도 `long_run`
- 실제 시간이 계획 시간과 가까움
- 날짜가 맞거나 허용 가능한 범위 안에 있음
- lap, pace, HR 패턴이 세션 의도와 크게 어긋나지 않음

점수가 낮다고 해서 항상 잘못한 것은 아닙니다. 예를 들어 다음 상황일 수 있습니다.

- 의도적으로 일정을 옮김
- 피로 때문에 세션을 줄임
- easy run이 너무 강해짐
- quality 세션이 base 수준으로 끝남
- 계획에 없던 세션을 수행함

이 점수는 단독 평가가 아니라 코치 해석의 입력으로 사용됩니다.

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

예시:

- 회복주를 사실상 강한 훈련처럼 뛰면 `excessive_stimulus`
- 품질훈련을 base 수준으로 끝내면 `reduced_stimulus`
- 같은 성격의 세션을 1~2일 늦게 수행하면 `schedule_shift`
- 적절한 계획 후보가 없는 추가 세션이면 `unplanned_session`

이 해석은 로그에만 남지 않고, 다음 주 계획에 다시 반영됩니다.

## Progression Model

코치는 현재 처방을 고정값으로 보지 않습니다. long run 거리, 인터벌 볼륨, 품질훈련 밀도, easy/base 페이스는 선수의 적응에 따라 바뀔 수 있습니다.

핵심 원칙은 다음과 같습니다.

`훈련 증가는 선수가 현재 부하를 흡수하고 있다고 판단될 때만 일어납니다.`

### Long run progression

Long run은 시간이 지나며 길어질 수 있지만, 기계적으로 늘리지 않습니다.

입력 신호:

- 최근 4~8주 러닝 볼륨
- 최근 7일 / 28일 부하
- 현재 훈련 블록
- 목표 레이스 거리
- long run 가능 요일과 시간
- 최근 long run 수행 품질
- long run 이후 회복 양상
- 피로도와 부상 리스크

예시:

- 주간 20~30km에 적응 중인 선수는 10~13km long run이 자연스러울 수 있습니다.
- 주간 40km에 잘 적응하면 14~18km도 가능할 수 있습니다.
- 하프마라톤이나 마라톤 준비라면 20km 이상 long run도 의미가 있을 수 있습니다.

다만 10K 목표에서는 길수록 항상 좋은 것은 아닙니다. Long run은 유산소 기반을 만들지만, 너무 큰 피로는 speed나 threshold 훈련 품질을 떨어뜨릴 수 있습니다.

### Quality session progression

인터벌과 threshold 세션은 여러 방식으로 발전할 수 있습니다.

- 반복 횟수 증가
- 반복 길이 증가
- 회복 시간 감소
- 목표 페이스 소폭 상승
- 총 품질훈련 시간 증가
- 주간 품질훈련 빈도 증가

예시:

- `6 x 1 min`
- `4 x 2 min`
- `5 x 400 m`
- `6 x 800 m`
- `5 x 1 km`
- `3 x 2 km threshold`

품질훈련은 최근 품질 세션이 실제로 잘 수행되고 회복이 안정적일 때만 늘리는 것이 맞습니다. 품질훈련이 반복해서 약하게 끝나거나, 과하게 수행되거나, 회복을 망가뜨리면 다음 계획은 progression보다 consolidation을 우선해야 합니다.

### Base run pace progression

Base run 페이스는 단순히 빨라지고 싶다고 강제로 올리는 것이 아닙니다.

의도한 원리는 다음과 같습니다.

- easy effort는 계속 easy여야 합니다.
- 유산소 능력이 좋아지면 같은 effort에서 페이스가 자연스럽게 빨라집니다.
- 코치는 페이스를 먼저 강제하기보다, 같은 HR/RPE에서 더 빨라지는 현상을 따라갑니다.

더 빠른 base 처방을 지지하는 신호:

- 비슷하거나 낮은 HR에서 더 빠른 페이스
- 낮은 HR drift
- 다음날 회복 안정
- 낮은 주관 RPE
- 부상이나 근육통 증가 없음

즉 base run은 `6:30/km`에서 `6:00/km` 또는 그 이상으로 자연스럽게 빨라질 수 있지만, 같은 effort가 여전히 easy일 때만 그렇게 조정하는 것이 맞습니다.

### Warmup / cooldown pace zone

웜업과 쿨다운에도 pace zone을 넣지만, 의도적으로 넓게 잡습니다.

메인 세트와 목적이 다릅니다.

- 웜업 pace zone은 너무 빠르게 시작하지 않도록 막는 역할입니다.
- 쿨다운 pace zone은 회복성 마무리를 유도하는 역할입니다.
- 타이트하게 맞춰야 하는 성과 목표가 아닙니다.

현재 Garmin 업로드 동작:

- 메인 러닝 target은 세션별 pace margin 사용
- 웜업 target은 더 넓은 margin 사용
- 쿨다운과 인터벌 recovery step은 가장 넓은 margin 사용

이렇게 하면 Garmin 가이드는 유지하면서도, 쉬운 전환 구간에서 시계 알림이 과하게 울리는 문제를 줄일 수 있습니다.

현재 margin 정책:

- interval: 좁게
- tempo / threshold: 비교적 좁게
- base run: 중간
- long run: 넓게
- recovery run: 넓게
- warmup: 넓게
- cooldown / recovery step: 가장 넓게

### Progression보다 consolidation을 우선하는 경우

엔진은 다음 신호가 있으면 훈련 증가보다 안정화를 우선해야 합니다.

- 높은 피로
- 나쁜 수면 또는 낮은 body battery
- 높은 부상 리스크
- recovery run이 너무 강하게 수행됨
- long run 후반이 과하게 강해짐
- quality 세션이 반복해서 약하게 끝남
- 비계획 hard 세션이 반복됨

이렇게 해야 시간이 지났다는 이유만으로 볼륨이나 강도를 올리는 문제를 피할 수 있습니다.

## Lap 기반 세션 품질 해석

엔진은 활동 내부를 보기 위해 lap / split 데이터도 사용합니다.

### 현재 activity profile 필드

- `avgPaceSeconds`
- `avgHr`
- `fastLapCount`
- `intervalLikeLapCount`
- `hrDrift`
- `latePaceChangeRatio`

### 이 신호가 의미하는 것

- 빠른 lap이 반복되거나 interval-like lap이 보이면 계획한 강한 자극이 실제로 들어갔을 가능성이 큽니다.
- 회복주에서 평균 심박이 높거나 빠른 lap이 반복되면 쉬운 날이 너무 강하게 수행된 것입니다.
- long run 후반에 페이스가 의미 있게 빨라지고 HR drift도 커지면 후반 강도가 과했던 것으로 볼 수 있습니다.

### executionQuality 예시

- `의도한 강도 자극이 잘 들어간 품질 세션`
- `품질 세션이지만 자극이 다소 약하게 들어감`
- `회복 세션치고 강도가 높았음`
- `지구력 자극이 충분한 장거리 세션`
- `롱런 후반 강도가 과하게 올라감`

### 왜 중요한가

엔진은 더 이상 단순히

- “long run이 있었는가?”

만 보지 않습니다. 이제는

- “의도한 품질 자극이 실제로 들어갔는가?”
- “회복주는 실제로 easy였는가?”
- “long run 후반이 과열되었는가?”

까지 봅니다.

이 품질 해석은 집계되어 다음 주 계획에 반영됩니다.

## 상태 추정

엔진은 세 개의 최상위 점수를 계산합니다.

- `readinessScore`
- `fatigueScore`
- `injuryRiskScore`

이 점수는 의학적 진단이 아니라 코칭용 신호입니다.

### readinessScore

점수가 높을수록 훈련을 흡수할 준비가 더 된 상태로 봅니다.

긍정 신호:

- 안정적인 chronic load
- 무리하지 않은 EWMA 비율
- 좋은 adherence
- 높은 body battery
- 좋은 수면과 HRV
- Garmin의 `PRODUCTIVE` 또는 안정적인 `MAINTAINING`
- 높은 의욕
- 최근 품질 세션이 실제로 잘 수행됨

부정 신호:

- 높은 최근 러닝 / 비러닝 부하
- 높은 monotony / strain
- 많은 미수행 또는 비계획 hard 세션
- 강한 주관 피로 / 근육통
- Garmin `OVERREACHING`, `UNPRODUCTIVE`, 높은 ACWR
- 회복주가 반복해서 너무 세게 수행됨

### fatigueScore

점수가 높을수록 최근 피로가 높다고 봅니다.

피로 상승 신호:

- 높은 최근 부하
- 긴 비러닝 운동 시간
- overload ratio 급등
- 높은 monotony / strain
- 높은 acute EWMA
- Garmin acute load 과부하 패턴
- 피로, 근육통, 스트레스 보고

피로 완화 신호:

- 높은 body battery
- 좋은 수면 점수

### injuryRiskScore

점수가 높을수록 보수적으로 계획해야 한다고 봅니다.

위험 상승 신호:

- overload ratio 급등
- 높은 monotony / strain
- 높은 acute EWMA
- Garmin acute/chronic 불균형
- 근육통, 피로, 통증 메모
- 활성 부상 심각도
- 강하게 끝나는 long run, 과한 자극 패턴 반복

위험 완화 신호:

- 안정적인 chronic load
- 안정적인 회복 신호

## 주간 Skeleton 규칙

LLM을 호출하기 전에 규칙 엔진이 아래를 먼저 정합니다.

- 러닝 일수
- 품질훈련 수
- long run 배치
- recovery / rest 배치
- 세션 시간 목표
- 가용 요일과 선호 요일 제약

### 현재 규칙 예시

- readiness가 낮거나 fatigue가 높으면 품질훈련을 줄이거나 제거합니다.
- 활성 부상이 있으면 볼륨을 줄이고 품질훈련을 제거합니다.
- 비계획 hard 세션이 반복되면 다음 주를 회복 쪽으로 기울입니다.
- reduced stimulus가 반복되면 이후 강도 기대치를 낮춥니다.
- 최근 품질훈련이 잘 수행되면 지나친 보수화를 막습니다.
- 회복주가 너무 세게 수행되면 easy day 통제를 더 강하게 합니다.
- long run 후반이 과열되면 다음 long run을 더 짧고 보수적으로 조정합니다.
- 최근 핵심 세션을 수행했다면 단기 회복 요구도를 높게 봅니다.
  가까운 quality나 long run은 회복, 피로, 부상, 실행 품질 신호가 안정적일 때만 허용합니다.
- long run은 주말과 사용자 선호 요일을 우선합니다.
- quality는 주중과 사용자 선호 요일을 우선합니다.
- 불가능한 요일은 무조건 휴식일로 고정합니다.
- 비러닝 부하가 높으면 러닝 일수와 품질훈련 수를 줄입니다.

즉 주간 구조의 바깥 경계는 코드가 먼저 고정합니다.

## LLM의 역할

LLM은 다음을 담당합니다.

- 세션 설명
- 워크아웃 step 상세
- 레이스 맥락 설명
- 코칭 문장 다듬기

LLM이 하면 안 되는 것:

- 날짜 변경
- 세션 타입 변경
- 위험한 볼륨 급증 생성
- 규칙, 부상, availability에서 나온 하드 제약 위반

생성 후에는 다시 정규화합니다.

- 잘못된 pace 형식 제거
- 0초 step 보정
- 잘못된 날짜나 이름 수정
- 명백히 잘못된 step은 안전한 fallback으로 교체

## 왜 이런 구조인가

이 아키텍처는 어느 한 방법만으로는 충분하지 않기 때문에 선택되었습니다.

### 왜 LLM 단독 계획이 아닌가

- 일관성이 떨어질 수 있습니다.
- 안전이 중요한 주간 구조를 신뢰하기 어렵습니다.
- 장기 제약이나 부하 규칙을 놓칠 수 있습니다.

### 왜 규칙만으로 하지 않는가

- 실제 선수 데이터는 너무 지저분하고 복합적입니다.
- planned vs actual, 회복 신호는 단순 임계값만으로 해석하기 어렵습니다.

### 왜 Garmin 값만 믿지 않는가

- Garmin은 좋은 신호를 주지만 전체 상태 모델은 아닙니다.
- 주관 피드백, 부상, 목표, 장기 히스토리 해석이 여전히 중요합니다.

현재 하이브리드 구조는 다음을 함께 사용합니다.

- **규칙 엔진**: 안전성과 일관성
- **DB**: 기억과 장기 맥락
- **Garmin**: 기기 기반 훈련 / 회복 신호
- **LLM**: 제한된 범위의 설명과 세션 디테일 생성

## 참고 근거

현재 설계는 특정 논문 하나를 그대로 구현한 것이 아니라, 코칭 실무와 athlete monitoring 문헌, workload 모델 비판을 함께 참고해 구성한 것입니다.

대표적으로 참고한 방향은 다음과 같습니다.

- acute:chronic workload ratio 하나에만 의존하는 접근의 한계
- EWMA 기반 workload 해석
- athlete monitoring 리뷰
- 수면과 회복 관련 문헌
- 계획 대비 실제 부하 차이에 대한 연구

목표는 특정 공식을 그대로 복제하는 것이 아니라, 실제 운영 가능한 보수적이고 설명 가능한 코치 엔진을 만드는 것입니다.
