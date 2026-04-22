# Coaching Algorithm

English | [한국어](COACHING_ALGORITHM.ko.md)

> **Note:** Two planner modes coexist, selected by `COACH_PLANNER_MODE`.
> - `legacy` (default, free tier) — algorithm builds a weekly skeleton, deterministic templates fill workout steps and Korean descriptions.
> - `llm_driven` (in burn-in) — LLM decides session placement/volume/duration, algorithm enforces safety via `SafetyValidator`.
>
> This document describes the `legacy` path. For the `llm_driven` split, see [Coaching Architecture](COACHING_ARCHITECTURE.md) §Planning Boundary.

## Purpose

Running Coach is not designed as an LLM-only workout generator. The coaching engine combines persistent athlete history, rule-based safety logic, deterministic legacy planning, and an optional bounded LLM-driven planner.

The design principle is:

`Code owns safety bounds and evidence normalization. In llm_driven mode, the LLM owns coaching prescription inside those hard bounds.`

Under `llm_driven` mode, the split shifts: code owns hard safety bounds (scoring, pace capability profile, pace safety bands, 15 safety rules), and the LLM owns coaching prescription (session placement, weekly volume, concrete pace prescription, phase interpretation).

This document explains what the engine looks at, how it turns raw data into planning signals, and why the current architecture was chosen.

## Coaching Layers

The system works in four layers:

1. **Data collection**
   Garmin and user inputs provide health, performance, activity, and constraint data.
2. **State storage and normalization**
   Postgres stores normalized history, not only raw payloads.
3. **Rule-based planning** (`legacy`) or **context assembly + safety validation** (`llm_driven`)
   Legacy: a weekly skeleton is generated from recovery, load, execution history, and constraints.
   LLM-driven: a `CoachingContext` is assembled and the LLM produces the plan; `SafetyValidator` auto-corrects violations.
4. **Workout assembly and validation**
   Legacy: deterministic step templates and Korean description templates fill the skeleton.
   LLM-driven: LLM output is parsed, validated, and corrected against the 15 safety rules.

## Data Inputs

### Garmin daily metrics

- `body_battery`
- `hrv`
- `sleep_score`
- `resting_hr`
- `training_status`
- `load_balance_phrase`
- `acute_load`
- `chronic_load`
- `acwr`

### Garmin performance metrics

- PRs
- VO2max
- lactate threshold pace and HR
- max HR

### Garmin activity history

- distance, duration, heart rate, elevation
- activity type
- laps and splits
- training-effect labels when available
- recent 7-day and 30-day running volume
- recent non-running duration

### User-provided constraints

- `availability_rules`
- `race_goals`
- `training_blocks`
- `subjective_feedback`
- `injury_status`

### Execution history

- `planned_workouts`
- `activities`
- `workout_executions`

## End-to-End Flow

1. Collect Garmin health, performance, activity, and scheduled-workout context
2. Normalize and persist data into Postgres
3. Rebuild planned-vs-actual execution links
4. Summarize recent load, long-term background, and current coaching state
5. Estimate `readinessScore`, `fatigueScore`, and `injuryRiskScore`
6. Build a rule-based 7-day weekly skeleton
7. Build workout steps and descriptions with deterministic legacy templates
8. Save plan rows and explainable decision rationale
9. Sync Garmin workouts and Google Calendar

In `auto` service mode, steps 6-9 are skipped when the active plan is still fresh. A replan is triggered when the plan horizon is missing, a new Garmin activity appeared after the last plan, recovery metrics materially worsened after the last plan, a key workout was missed, or base-volume misses accumulated. A single missed recovery run is treated as extra rest and does not replan by itself.

Main implementation:

- `src/running_coach/storage/history_service.py`
- `src/running_coach/clients/gemini/planner.py`
- `src/running_coach/core/orchestrator.py`

## Load Model

The engine does not look only at recent running distance. It builds a mixed load model that includes both running and non-running work.

### Daily load definition

- running load: total running distance in km for that day
- cross-training load: non-running duration in seconds divided by `600`
- total daily load:
  - `running_km + non_running_seconds / 600`

This is intentionally conservative. Cycling, hiking, and strength work are not converted into a fake running equivalent; they are treated as additional load signals.

### Derived load signals

The system computes:

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

### Garmin-native hybrid load

The database model is not used alone. Garmin-native signals are used as a correction layer:

- `trainingStatus`
- `loadBalancePhrase`
- `garminAcuteLoad`
- `garminChronicLoad`
- `garminAcwr`

Interpretation principle:

- the DB-based model is the primary normalized history model
- Garmin-native load is a secondary correction signal
- Garmin metrics do not override explicit injury, pain, or strong subjective fatigue inputs

This hybrid design reduces dependence on any single model.

## Recovery Model

Recovery is estimated from both objective device data and subjective athlete feedback.

### Recovery inputs

- `body_battery`
- `sleep_score`
- `hrv`
- `training_status`
- `load_balance_phrase`
- subjective fatigue
- soreness
- stress
- sleep quality
- motivation
- active injury severity

### Recovery principles

- objective and subjective signals are combined
- good device recovery does not cancel strong soreness or pain
- high recent load is not always bad if recovery signals remain stable
- injury severity is treated as a hard conservatism signal

## Planned-vs-Actual Interpretation

Professional coaching requires more than “did the athlete run?” The engine tries to understand how actual execution differed from the intended session.

### Matching logic

Each completed activity is matched to the most plausible planned workout using:

- date proximity: `-2 days to +3 days`
- planned-vs-actual category similarity
- duration similarity
- whether the planned candidate was already matched

### Session categories

- `recovery`
- `base`
- `long_run`
- `quality`
- `unplanned`

### Stored execution fields

- `completion_ratio`
- `target_match_score`
- `executionStatus`
- `deviationReason`
- `coachInterpretation`
- `executionQuality`

### Execution match score

`target_match_score` is a planned-vs-actual match score. It is not a fitness score, race predictor, or judgment of whether the workout was impressive.

It answers:

- “Did the athlete execute the planned session intent?”

For example, a score of `0.98` means the completed workout was very close to the planned workout. In a long-run case, that usually means:

- the planned category was `long_run`
- the actual category was also `long_run`
- actual duration was close to planned duration
- the date was correct or close enough
- lap, pace, and HR patterns did not strongly contradict the intended session

Low scores do not always mean the athlete did something wrong. They can mean:

- the session was intentionally moved
- a workout was shortened because of fatigue
- an easy run became too hard
- a quality session became a base run
- the athlete did an unplanned session

The score is used as an input to coaching interpretation, not as a standalone grade.

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

Examples:

- a recovery run executed like a hard session becomes `excessive_stimulus`
- a quality session executed like a base run becomes `reduced_stimulus`
- a similar workout performed one or two days late becomes `schedule_shift`
- an extra session with no reasonable planned match becomes `unplanned_session`

These interpretations do not stay in logs only. They feed back into the next weekly plan.

## Progression Model

The coach does not treat current workout prescriptions as fixed. Long-run distance, interval volume, quality-session density, and easy pace can all change as the athlete adapts.

The key principle is:

`Progression happens only when the athlete appears to absorb the current load.`

### Long-run progression

Long runs can grow over time, but they are not increased mechanically.

Inputs:

- recent 4-8 week running volume
- recent 7-day and 28-day load
- current training block
- target race distance
- availability on long-run days
- recent long-run execution quality
- recovery after long runs
- fatigue and injury-risk signals

Examples:

- an athlete around 20-30 km/week may receive a long run around 10-13 km
- an athlete adapted to 40 km/week may receive 14-18 km
- half-marathon or marathon preparation may justify 20 km+ long runs

For a 10K goal, longer is not always better. A long run supports aerobic durability, but too much long-run fatigue can reduce the quality of speed or threshold work.

### Quality-session progression

Intervals and threshold sessions can progress through several dimensions:

- more repetitions
- longer repetitions
- shorter recovery
- slightly faster target pace
- longer total quality duration
- higher weekly quality frequency

Examples:

- `6 x 1 min`
- `4 x 2 min`
- `5 x 400 m`
- `6 x 800 m`
- `5 x 1 km`
- `3 x 2 km threshold`

The system should increase quality only when recent quality work was executed well and recovery remained stable. If quality work repeatedly becomes reduced stimulus, excessive stimulus, or causes poor recovery, the next plan should consolidate rather than progress.

### Base-run pace progression

Base-run pace should not be forced faster just because the athlete wants to improve.

The intended logic is:

- easy effort stays easy
- pace improves naturally as aerobic fitness improves
- the coach follows better pace at the same HR/RPE, rather than forcing pace first

Signals that support faster base prescriptions:

- similar or lower HR at faster pace
- lower HR drift
- stable next-day recovery
- low subjective RPE
- no injury or soreness increase

This means a base run might gradually move from `6:30/km` to `6:00/km` or faster, but only if the same effort remains genuinely easy.

### Personalized pace capability profile

Workout pace targets are no longer fixed constants. In `legacy` mode, the planner still uses `PaceZoneEngine` center paces to fill deterministic workout steps. In `llm_driven` mode, the prompt receives a pace capability profile: threshold evidence, reference center paces, and safety bands. The LLM chooses concrete target paces inside those bands.

Priority order:

- Garmin lactate-threshold pace
- configured race target pace
- inferred threshold pace from PRs such as 5K, 10K, half marathon, or marathon
- conservative default threshold pace when no pace data exists

The engine calculates reference center paces and safety bands for:

- interval
- threshold / tempo
- base / long run
- recovery
- warmup / cooldown

Garmin still receives a pace zone around each selected target. In `llm_driven` mode, the selected target pace comes from the LLM and `PaceBandIntegrity` only clamps values that fall outside the safety band. `WorkoutManager` then applies session-specific margins for Garmin.

### Warmup and cooldown pace zones

Warmup and cooldown steps also use pace zones, but they are intentionally loose.

Their purpose is different from the main set:

- warmup pace zones prevent starting too fast
- cooldown pace zones encourage an easy finish
- they are not meant to be tight performance targets

Current Garmin upload behavior:

- main running targets use session-specific pace margins
- warmup targets use a wider margin
- cooldown and interval-recovery targets use the widest margins

This keeps Garmin guidance useful without making the watch too noisy during easy transitions.

Current margin policy:

- interval: narrow
- tempo / threshold: moderately narrow
- base run: moderate
- long run: wider
- recovery run: wide
- warmup: wide
- cooldown and recovery steps: widest

### Consolidation before progression

The engine should prefer consolidation over progression when it sees:

- high fatigue
- poor sleep or low body battery
- elevated injury risk
- recovery runs executed too hard
- long runs finished too aggressively
- repeated reduced-stimulus quality sessions
- repeated unplanned hard sessions

This prevents the system from increasing volume or intensity simply because time has passed.

## Lap-Based Execution Quality

The engine also looks inside activities using lap and split data.

### Current activity profile fields

- `avgPaceSeconds`
- `avgHr`
- `fastLapCount`
- `intervalLikeLapCount`
- `hrDrift`
- `latePaceChangeRatio`

### What these signals mean

- repeated fast laps or interval-like laps suggest that the planned hard stimulus actually happened
- high average HR or repeated fast laps during a recovery run suggest that the easy session was too hard
- a long run whose second half becomes meaningfully faster while HR drift rises may be too aggressive late in the session

### executionQuality examples

- `의도한 강도 자극이 잘 들어간 품질 세션`
- `품질 세션이지만 자극이 다소 약하게 들어감`
- `회복 세션치고 강도가 높았음`
- `지구력 자극이 충분한 장거리 세션`
- `롱런 후반 강도가 과하게 올라감`

### Why this matters

The engine is no longer asking only:

- “Was there a quality session?”

It also asks:

- “Was the intended quality stimulus actually achieved?”
- “Was the recovery session actually easy?”
- “Did the long run get out of control late?”

These quality interpretations are aggregated and fed into next-week planning.

## State Estimation

The engine computes three top-level coaching scores:

- `readinessScore`
- `fatigueScore`
- `injuryRiskScore`

These are coaching signals, not medical diagnoses.

### readinessScore

Higher means the athlete is more ready to absorb training.

Positive signals:

- stable chronic load
- reasonable EWMA ratio
- good adherence
- high body battery
- good sleep and HRV
- Garmin `PRODUCTIVE` or stable `MAINTAINING` signals
- strong motivation
- recent quality sessions executed well

Negative signals:

- high recent running and non-running load
- high monotony or strain
- many skipped or unplanned hard sessions
- strong subjective fatigue or soreness
- Garmin `OVERREACHING`, `UNPRODUCTIVE`, or high Garmin ACWR
- recovery sessions repeatedly executed too hard

### fatigueScore

Higher means recent fatigue is likely elevated.

Positive fatigue signals:

- high recent load
- high cross-training duration
- overload-ratio spikes
- high monotony or strain
- elevated acute EWMA
- Garmin acute-load overload patterns
- fatigue, soreness, or stress reports

Negative fatigue signals:

- high body battery
- good sleep score

### injuryRiskScore

Higher means the engine should be more conservative.

Positive risk signals:

- overload-ratio spikes
- high monotony or strain
- high acute EWMA
- Garmin acute/chronic imbalance
- soreness, fatigue, pain notes
- active injury severity
- repeated hard long-run endings or excessive-stimulus patterns

Negative risk signals:

- stable chronic load
- stable recovery signals

## Weekly Skeleton Rules

Before the LLM is called, a rule engine decides:

- number of run days
- number of quality sessions
- long-run placement
- recovery and rest placement
- session-duration targets
- availability and preferred-day constraints

### Examples of current rules

- low readiness or high fatigue removes or reduces quality
- active injury reduces volume and removes quality
- repeated unplanned hard work pushes the next week toward recovery
- repeated reduced-stimulus sessions lower future intensity expectations
- well-executed quality sessions prevent the engine from becoming too conservative
- recovery sessions that were too hard make the next week stricter on easy-day control
- long runs finished too hard shorten the next long run and reduce intensity pressure
- recent key sessions increase short-term recovery demand; close follow-up quality or long-run
  sessions are allowed only when recovery, fatigue, injury, and execution-quality signals are stable
- long runs prefer weekend and user-preferred long-run days
- quality prefers mid-week and user-preferred quality days
- unavailable weekdays are forced to rest
- high cross-training load reduces run days and quality count

The LLM does not own the weekly structure. It operates inside this boundary.

## LLM Role

The LLM is used for:

- workout descriptions
- workout-step detail
- canonical workout type selection (`Interval`, `Threshold`, `Tempo Run`, `Fartlek`,
  etc.) inside the allowed `sessionType`
- race-context explanation
- coaching-language refinement

The LLM is not allowed to:

- move dates
- change session type
- create unsafe volume spikes
- break hard constraints from rules, injuries, or availability

After generation, output is normalized again:

- invalid pace formats are removed
- zero-duration steps are fixed
- wrong dates or workout names are corrected
- `workoutType`, `sessionType`, and `workout.workoutName` are expected to match the
  workout catalog; the safety layer still corrects mismatches as a final guard
- a single long `Interval` step at threshold or tempo pace is normalized as a continuous
  `Run` block and named `Threshold` or `Tempo Run`
- invalid steps can be replaced by safe fallbacks

## Why This Design

This architecture exists because none of the single-layer alternatives are good enough.

### Why not LLM-only planning?

- it is less consistent
- it is harder to trust for safety-critical structure
- it can ignore long-term constraints or produce unstable plans

### Why not rules only?

- rules alone struggle to interpret messy real-world athlete context
- planned-vs-actual behavior and recovery signals need interpretation, not only threshold checks

### Why not Garmin-only?

- Garmin provides valuable signals but is not the full state model
- subjective feedback, injuries, goals, and historical coaching interpretation still matter

The current hybrid model uses:

- **rules** for safety and consistency
- **the database** for memory and longitudinal context
- **Garmin** for device-derived training and recovery signals
- **the LLM** for bounded explanation and workout-detail generation

## External References

This design is informed by coaching practice, athlete-monitoring literature, and workload-model critiques rather than any single paper.

Representative references include:

- acute:chronic workload critique and limits of single-ratio thinking
- EWMA-based workload proposals
- athlete-monitoring reviews
- sleep and recovery literature
- planned-vs-actual training-load mismatch studies

The goal is not to implement one academic formula literally. The goal is to combine robust practical signals into a conservative, explainable coaching engine.
