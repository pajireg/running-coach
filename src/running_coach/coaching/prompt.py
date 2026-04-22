"""LLM 프롬프트 렌더러.

CoachingContext + safety rules 설명 → Gemini 에 보낼 문자열.
순수 렌더러: threshold 해석이나 법칙 도출은 하지 않는다.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from ..core.pace_zones import PaceCapabilityProfile
from .context import CoachingContext, CoachingScores

if TYPE_CHECKING:
    from ..models.training import DailyPlan


def _score_hint(score: float) -> str:
    """점수 해석 hint (threshold 구간 대신 정성적 한 단어)."""
    if score >= 75:
        return "매우 높음"
    if score >= 60:
        return "보통 이상"
    if score >= 40:
        return "보통"
    if score >= 25:
        return "낮음"
    return "매우 낮음"


def _scores_block(scores: CoachingScores) -> str:
    lines = [
        f"- 회복도 {scores.readiness:.0f} ({_score_hint(scores.readiness)})",
        f"- 피로도 {scores.fatigue:.0f} ({_score_hint(scores.fatigue)})",
        f"- 부상 리스크 {scores.injury_risk:.0f} ({_score_hint(scores.injury_risk)})",
    ]
    if scores.active_injury_severity > 0:
        lines.append(f"- 활성 부상 severity {scores.active_injury_severity}")
    if scores.chronic_ewma_load > 0:
        lines.append(f"- chronic EWMA load {scores.chronic_ewma_load:.1f}km")
    return "\n".join(lines)


def _execution_rows(ctx: CoachingContext) -> list[dict[str, Any]]:
    """실행 이력을 JSON 친화 dict 로 변환 (raw, 해석 없음)."""
    rows: list[dict[str, Any]] = []
    for item in ctx.execution_history_14d:
        rows.append(
            {
                "date": item.date.isoformat(),
                "plannedCategory": item.planned_category,
                "actualCategory": item.actual_category,
                "distanceKm": item.distance_km,
                "durationSeconds": item.duration_seconds,
                "avgPace": item.avg_pace,
                "avgHr": item.avg_hr,
                "executionStatus": item.execution_status,
                "deviationReason": item.deviation_reason,
                "matchScore": item.match_score,
            }
        )
    return rows


def _feedback_rows(ctx: CoachingContext) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for fb in ctx.recent_feedback:
        out.append(
            {
                "feedbackDate": fb.feedback_date.isoformat() if fb.feedback_date else None,
                "fatigueScore": fb.fatigue_score,
                "sorenessScore": fb.soreness_score,
                "stressScore": fb.stress_score,
                "motivationScore": fb.motivation_score,
                "sleepQualityScore": fb.sleep_quality_score,
                "painNotes": fb.pain_notes,
                "notes": fb.notes,
                "stalenessDays": fb.staleness_days,
            }
        )
    return out


def _availability_rows(ctx: CoachingContext) -> list[dict[str, Any]]:
    return [
        {
            "weekday": wd,
            "isAvailable": slot.is_available,
            "maxDurationMinutes": slot.max_duration_minutes,
            "preferredSessionType": slot.preferred_session_type,
        }
        for wd, slot in sorted(ctx.availability.items())
    ]


def _placement_constraints(ctx: CoachingContext) -> dict[str, Any]:
    plan_dates = [ctx.today + timedelta(days=i) for i in range(7)]
    preferred_long_run_weekdays = sorted(
        weekday
        for weekday, slot in ctx.availability.items()
        if slot.is_available and slot.preferred_session_type == "long_run"
    )
    long_run_allowed_dates = [
        {
            "date": d.isoformat(),
            "weekday": d.weekday(),
            "maxDurationMinutes": ctx.availability_for(d.weekday()).max_duration_minutes,
        }
        for d in plan_dates
        if d.weekday() in preferred_long_run_weekdays
    ]
    return {
        "longRunPlacementPolicy": (
            "If longRunAllowedDates is non-empty, Long Run MUST be placed on one of those dates."
        ),
        "preferredLongRunWeekdays": preferred_long_run_weekdays,
        "longRunAllowedDates": long_run_allowed_dates,
    }


def _active_injury_dict(ctx: CoachingContext) -> dict[str, Any]:
    inj = ctx.active_injury
    if not inj.is_active:
        return {}
    return {
        "injuryArea": inj.injury_area,
        "severity": inj.severity,
        "statusDate": inj.status_date.isoformat() if inj.status_date else None,
        "notes": inj.notes,
    }


def _training_block_dict(ctx: CoachingContext) -> dict[str, Any] | None:
    if ctx.training_block is None:
        return None
    b = ctx.training_block
    weeks_until_race = None
    if ctx.race_goal and ctx.race_goal.race_date:
        weeks_until_race = max(0, (ctx.race_goal.race_date - ctx.today).days // 7)
    return {
        "phase": b.phase,
        "focus": b.focus,
        "weeklyVolumeTargetKm": b.weekly_volume_target_km,
        "startsOn": b.starts_on.isoformat() if b.starts_on else None,
        "endsOn": b.ends_on.isoformat() if b.ends_on else None,
        "weeksUntilRace": weeks_until_race,
    }


def _race_goal_dict(ctx: CoachingContext) -> dict[str, Any] | None:
    if ctx.race_goal is None:
        return None
    r = ctx.race_goal
    return {
        "goalName": r.goal_name,
        "raceDate": r.race_date.isoformat() if r.race_date else None,
        "distance": r.distance,
        "goalTime": r.goal_time,
        "targetPace": r.target_pace,
    }


def _training_background_dict(ctx: CoachingContext) -> dict[str, Any]:
    return {
        "recent6Weeks": ctx.training_background.recent_6_weeks,
        "recent12Months": ctx.training_background.recent_12_months,
        "lifetime": ctx.training_background.lifetime,
    }


def _pace_capability_dict(ctx: CoachingContext) -> dict[str, object]:
    profile = ctx.pace_profile or PaceCapabilityProfile.from_zones(ctx.pace_zones)
    return profile.to_prompt_dict()


WORKOUT_CATALOG = {
    "Rest Day": {
        "sessionType": "rest",
        "stepContract": "steps 는 비우거나 Rest step 만 사용",
        "paceIntent": "완전 휴식",
    },
    "Recovery Run": {
        "sessionType": "recovery",
        "stepContract": "Warmup + Run + Cooldown, main Run 은 recovery pace",
        "paceIntent": "매우 편안한 회복 주",
    },
    "Base Run": {
        "sessionType": "base",
        "stepContract": "Warmup + Run + Cooldown, main Run 은 base pace",
        "paceIntent": "유산소 기반과 주간 볼륨",
    },
    "Interval": {
        "sessionType": "quality",
        "stepContract": (
            "반복 Interval step + Recovery step. Interval 반복 구간은 동일 duration. "
            "단일 10분 이상 continuous Interval step 금지"
        ),
        "paceIntent": "VO2max/무산소 자극, interval pace",
    },
    "Threshold": {
        "sessionType": "quality",
        "stepContract": (
            "Warmup + Run(+Recovery+Run 가능) + Cooldown. "
            "threshold 페이스 continuous 또는 split Run block. Interval step 금지"
        ),
        "paceIntent": "젖산 역치 능력, threshold pace",
    },
    "Tempo Run": {
        "sessionType": "quality",
        "stepContract": "Warmup + Run + Cooldown. tempo 페이스 continuous Run. Interval step 금지",
        "paceIntent": "지속력과 race-supporting aerobic strength, tempo pace",
    },
    "Fartlek": {
        "sessionType": "quality",
        "stepContract": (
            "Interval step + Recovery step 반복. Interval duration 을 불규칙하게 구성 "
            "(가장 긴 반복이 가장 짧은 반복의 1.5배 이상)"
        ),
        "paceIntent": "변속 적응과 부담을 낮춘 quality",
    },
    "Long Run": {
        "sessionType": "long_run",
        "stepContract": "Warmup + Run + Cooldown, main Run 은 long_run pace",
        "paceIntent": "지구력과 fatigue resistance",
    },
}


OUTPUT_SCHEMA = {
    "weekly": {
        "summaryKo": "string (3-5문장, 한국어)",
        "phase": "base|build|peak|taper|maintenance",
        "phaseReasonKo": "string (한국어)",
        "weeklyVolumeTargetKm": "number > 0",
        "riskAcknowledgements": ["string"],
    },
    "plan": [
        {
            "date": "YYYY-MM-DD",
            "sessionType": "rest|recovery|base|quality|long_run",
            "workoutType": (
                "Rest Day|Recovery Run|Base Run|Interval|Threshold|Tempo Run|Fartlek|" "Long Run"
            ),
            "plannedMinutes": "integer >= 0",
            "workout": {
                "workoutName": "must exactly equal workoutType",
                "description": (
                    "string (한국어 2-3문장: 오늘 이 훈련을 하는 이유, 좋아지는 능력, "
                    "실행 포인트 포함)"
                ),
                "sportType": "RUNNING",
                "steps": [
                    {
                        "type": "Warmup|Run|Interval|Recovery|Cooldown|Rest",
                        "durationValue": "integer seconds > 0",
                        "durationUnit": "second",
                        "targetType": "no_target|speed",
                        "targetValue": "MM:SS (targetType=speed 일 때)",
                    }
                ],
            },
        }
    ],
}


def _as_json(value: Any) -> str:
    """결정적 직렬화 (sort_keys) — prompt cache 친화."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class LLMPromptTemplate:
    """CoachingContext + safety 룰 설명 → Gemini 입력 문자열."""

    @classmethod
    def render(
        cls,
        ctx: CoachingContext,
        safety_rules: list[str],
        include_strength: bool = False,
    ) -> str:
        end_date = ctx.today + timedelta(days=6)
        sections: list[str] = []

        sections.append("당신은 시니어 러닝 코치입니다. 선수에게 7일 훈련 계획을 설계합니다.")
        sections.append(f"[오늘] {ctx.today.isoformat()} / 계획 종료일 {end_date.isoformat()}")

        if ctx.metrics is not None:
            gemini_metrics = ctx.metrics.to_gemini_dict()
            sections.append(f"[오늘 지표 (health)] {_as_json(gemini_metrics.get('health') or {})}")
            sections.append(f"[퍼포먼스] {_as_json(gemini_metrics.get('performance') or {})}")
            sections.append(
                f"[컨텍스트 (어제 실제 vs 계획)] {_as_json(gemini_metrics.get('context') or {})}"
            )

        sections.append("[스코어]\n" + _scores_block(ctx.scores))

        sections.append(
            "[페이스 능력 프로파일]\n"
            "referenceCenters 는 참고값이고 safetyBands 는 허용 범위입니다. "
            "targetValue 는 선수 상태와 세션 의도에 맞춰 safetyBands 안에서 선택하세요.\n"
            + _as_json(_pace_capability_dict(ctx))
        )

        sections.append("[지난 14일 실제 수행 이력 (raw)]\n" + _as_json(_execution_rows(ctx)))

        active_inj = _active_injury_dict(ctx)
        sections.append("[활성 부상] " + _as_json(active_inj))

        sections.append("[최근 주관적 피드백] " + _as_json(_feedback_rows(ctx)))

        sections.append("[대회 컨텍스트] " + _as_json(_race_goal_dict(ctx)))

        sections.append("[훈련 블록] " + _as_json(_training_block_dict(ctx)))

        sections.append("[재계획 트리거 사유] " + _as_json(ctx.replan_reasons))

        sections.append("[주간 가용성] " + _as_json(_availability_rows(ctx)))
        sections.append("[세션 배치 하드 제약] " + _as_json(_placement_constraints(ctx)))

        sections.append("[훈련 배경] " + _as_json(_training_background_dict(ctx)))

        rules_block = "\n".join(f"- {line}" for line in safety_rules)
        sections.append("[반드시 지켜야 할 안전 원칙]\n" + rules_block)

        sections.append(
            "[훈련 카탈로그 — 선수 수준/회복 상태에 맞춰 선택]\n" + _as_json(WORKOUT_CATALOG) + "\n"
            "세션 선택 가이드:\n"
            "- 각 날짜는 먼저 workoutType 을 위 카탈로그의 8개 canonical name 중 "
            "하나로 선택하세요.\n"
            "- workout.workoutName 은 반드시 workoutType 과 정확히 같은 문자열이어야 합니다.\n"
            "- sessionType 은 선택한 workoutType 의 sessionType 과 정확히 일치해야 합니다.\n"
            "- readiness 가 높고 chronic load 충분: Interval 또는 Threshold 로 능력 자극.\n"
            "- 피로/부상 지표 경계선: Tempo Run 또는 Fartlek 으로 완충.\n"
            "- 최근 quality 수행력이 약했다면 이번 주는 Threshold 나 Tempo 로 base building.\n"
            "- 대회까지 남은 기간 / phase 에 맞춰 특이성(race pace 근접) 조절.\n"
            "- Threshold/Tempo Run 은 continuous quality 이므로 main work 에 Run step 을 쓰고 "
            "Interval step 을 쓰지 마세요.\n"
            "- Interval 은 반복 인터벌일 때만 사용하세요. 10분 이상 단일 continuous block 은 "
            "Threshold 또는 Tempo Run 으로 선택하세요."
        )

        sections.append(
            "[코치 설명 작성 규칙]\n"
            "각 workout.description 은 한국어 2-3문장으로 작성하세요.\n"
            "- 오늘 이 훈련을 배치한 이유를 설명하세요.\n"
            "- 어떤 능력이 좋아지는지 구체적으로 말하세요 "
            "(예: 유산소 기반, 피로 저항력, 젖산 역치, 페이스 감각, 회복).\n"
            "- 사용자가 실행 중 지킬 포인트를 한 문장으로 덧붙이세요.\n"
            "- 한 구절짜리 일반 설명이나 workoutType 반복만 쓰지 마세요."
        )

        if include_strength:
            sections.append(
                "[근력 훈련 참고]\n"
                "러닝 세션의 workout.description 필드에 한국어로 보조 근력 조언을 덧붙이세요.\n"
                "(steps 에는 러닝 step 만 포함; sportType 은 반드시 RUNNING.)"
            )
        else:
            sections.append("[근력 훈련]\n러닝만 계획하고 steps 에 근력 세션을 넣지 마세요.")

        sections.append(
            "[결정 과제]\n"
            "1. 이번 주 weekly_volume_target_km 를 결정하세요.\n"
            "2. 7일 각각의 workoutType 을 카탈로그에서 선택하고 sessionType 을 맞추세요.\n"
            "3. 각 일자의 plannedMinutes 를 결정하세요.\n"
            "4. 각 세션의 step 구조와 targetValue 페이스를 설계하세요. "
            "페이스는 safetyBands 안에서 선택하되 referenceCenters 를 그대로 "
            "복사할 필요는 없습니다.\n"
            "5. weekly.summaryKo (3-5문장, 한국어)와 phase / phaseReasonKo 를 작성하세요."
        )

        sections.append("[출력 스키마]\n" + _as_json(OUTPUT_SCHEMA))
        sections.append("Return ONLY valid JSON matching the schema.")

        return "\n\n".join(sections)

    @classmethod
    def render_extend(
        cls,
        ctx: CoachingContext,
        existing_days: "list[DailyPlan]",
        new_date: date,
        safety_rules: list[str],
        include_strength: bool = False,
    ) -> str:
        """기존 6일 확정 + 신규 1일만 설계하는 extend 프롬프트."""
        locked = [
            {
                "date": d.date.isoformat(),
                "sessionType": d.session_type,
                "plannedMinutes": d.planned_minutes,
                "workoutName": d.workout.workout_name,
            }
            for d in existing_days
        ]

        sections: list[str] = []
        sections.append("당신은 시니어 러닝 코치입니다.")
        sections.append(
            f"[오늘] {ctx.today.isoformat()} — 오늘 훈련이 정상 이수되어 "
            "호라이즌을 하루 연장합니다."
        )

        if ctx.metrics is not None:
            gemini_metrics = ctx.metrics.to_gemini_dict()
            sections.append(f"[오늘 지표 (health)] {_as_json(gemini_metrics.get('health') or {})}")
            sections.append(f"[퍼포먼스] {_as_json(gemini_metrics.get('performance') or {})}")

        sections.append("[스코어]\n" + _scores_block(ctx.scores))
        sections.append(
            "[페이스 능력 프로파일]\n"
            "referenceCenters 는 참고값이고 safetyBands 는 허용 범위입니다. "
            "targetValue 는 새 세션 의도에 맞춰 safetyBands 안에서 선택하세요.\n"
            + _as_json(_pace_capability_dict(ctx))
        )
        sections.append("[지난 14일 실제 수행 이력 (raw)]\n" + _as_json(_execution_rows(ctx)))

        active_inj = _active_injury_dict(ctx)
        sections.append("[활성 부상] " + _as_json(active_inj))
        sections.append("[주간 가용성] " + _as_json(_availability_rows(ctx)))
        sections.append("[세션 배치 하드 제약] " + _as_json(_placement_constraints(ctx)))
        sections.append("[최근 주관적 피드백] " + _as_json(_feedback_rows(ctx)))
        sections.append("[훈련 블록] " + _as_json(_training_block_dict(ctx)))
        sections.append("[대회 컨텍스트] " + _as_json(_race_goal_dict(ctx)))

        rules_block = "\n".join(f"- {line}" for line in safety_rules)
        sections.append("[반드시 지켜야 할 안전 원칙]\n" + rules_block)

        sections.append("[확정된 6일 세션 — 이 세션들은 변경하지 마세요]\n" + _as_json(locked))
        sections.append(
            "[훈련 카탈로그]\n" + _as_json(WORKOUT_CATALOG) + "\n"
            "새 날짜는 workoutType 을 위 8개 canonical name 중 하나로 선택하고, "
            "workout.workoutName 은 workoutType 과 정확히 같게 쓰세요. "
            "Threshold/Tempo Run 은 main work 에 Run step 을 쓰고 Interval step 을 쓰지 마세요."
        )
        sections.append(
            f"[결정 과제]\n"
            f"{new_date.isoformat()} 1일치 세션만 새로 설계하세요.\n"
            "위 확정 세션과 연결되는 흐름을 고려하여 sessionType, workoutType, plannedMinutes, "
            "step 구조를 결정하세요."
        )
        sections.append(
            "[코치 설명 작성 규칙]\n"
            "workout.description 은 한국어 2-3문장으로 작성하세요. "
            "오늘 이 훈련을 하는 이유, 좋아지는 능력, 실행 포인트를 모두 포함하고 "
            "한 구절짜리 일반 설명은 쓰지 마세요."
        )
        if include_strength:
            sections.append(
                "[근력 훈련 참고]\n"
                "workout.description 에 한국어 보조 근력 조언을 덧붙이세요.\n"
                "(steps 에는 러닝 step 만; sportType 은 반드시 RUNNING.)"
            )
        else:
            sections.append("[근력 훈련]\n러닝만 계획하고 steps 에 근력 세션을 넣지 마세요.")

        single_day_schema = {
            "date": "YYYY-MM-DD",
            "sessionType": "rest|recovery|base|quality|long_run",
            "workoutType": (
                "Rest Day|Recovery Run|Base Run|Interval|Threshold|Tempo Run|Fartlek|" "Long Run"
            ),
            "plannedMinutes": "integer >= 0",
            "workout": OUTPUT_SCHEMA["plan"][0]["workout"],  # type: ignore[index]
        }
        sections.append("[출력 스키마 — 단일 DailyPlan JSON 객체]\n" + _as_json(single_day_schema))
        sections.append("Return ONLY valid JSON matching the schema.")

        return "\n\n".join(sections)

    @classmethod
    def context_as_dict(cls, ctx: CoachingContext) -> dict[str, Any]:
        """디버깅·스냅샷 테스트용 dict 표현."""
        return {
            "today": ctx.today.isoformat(),
            "scores": asdict(ctx.scores),
            "paceZones": ctx.pace_zones.to_dict(),
            "paceCapability": _pace_capability_dict(ctx),
            "workoutCatalog": WORKOUT_CATALOG,
            "availability": _availability_rows(ctx),
            "placementConstraints": _placement_constraints(ctx),
            "executionHistory14d": _execution_rows(ctx),
            "activeInjury": _active_injury_dict(ctx),
            "recentFeedback": _feedback_rows(ctx),
            "trainingBlock": _training_block_dict(ctx),
            "raceGoal": _race_goal_dict(ctx),
            "trainingBackground": _training_background_dict(ctx),
            "replanReasons": list(ctx.replan_reasons),
        }


def example_date() -> date:
    """테스트·문서용 고정 날짜."""
    return date(2026, 4, 20)
