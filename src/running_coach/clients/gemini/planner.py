"""legacy skeleton 기반 계획 생성에 쓰이는 알고리즘 유틸.

`LegacySkeletonPlanner` 가 `_build_weekly_skeleton` 으로 주 7일 배치와
볼륨을 결정한다. LLM 호출은 `LLMDrivenPlanner` 가 전담하며 이 모듈은
Gemini API 를 직접 호출하지 않는다.
"""

from datetime import timedelta
from typing import Any, Optional, cast

from google import genai

from ...core.pace_zones import PaceZoneEngine
from ...models.config import RaceConfig
from ...models.metrics import AdvancedMetrics
from ...utils.logger import get_logger

logger = get_logger(__name__)


class TrainingPlanner:
    """legacy skeleton 알고리즘 유틸."""

    def __init__(self, gemini_client: genai.Client):
        """
        Args:
            gemini_client: genai.Client 인스턴스 (현재 미사용; 향후 호환성 위해 유지)
        """
        self.client = gemini_client

    def _build_weekly_skeleton(
        self,
        metrics: AdvancedMetrics,
        race_config: RaceConfig,
        training_background: Optional[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """규칙 기반으로 7일 skeleton 생성."""
        start_date = metrics.date
        state = cast(dict[str, Any], (training_background or {}).get("coachingState") or {})
        constraints = cast(
            dict[str, Any], (training_background or {}).get("planningConstraints") or {}
        )
        readiness = float(state.get("readinessScore") or 50.0)
        fatigue = float(state.get("fatigueScore") or 50.0)
        injury = float(state.get("injuryRiskScore") or 20.0)
        load_state = cast(dict[str, Any], state.get("load") or {})
        raw_days_since_long_run = load_state.get("daysSinceLongRun")
        days_since_long_run = (
            raw_days_since_long_run if isinstance(raw_days_since_long_run, int) else None
        )
        raw_days_since_quality = load_state.get("daysSinceQuality")
        days_since_quality = (
            raw_days_since_quality if isinstance(raw_days_since_quality, int) else None
        )
        active_injury = cast(dict[str, Any], state.get("activeInjury") or {})
        active_injury_severity = int(active_injury.get("severity") or 0)
        execution_insights = cast(dict[str, Any], state.get("executionInsights") or {})
        reduced_stimulus_count = int(execution_insights.get("reducedStimulusCount") or 0)
        excessive_stimulus_count = int(execution_insights.get("excessiveStimulusCount") or 0)
        schedule_shift_count = int(execution_insights.get("scheduleShiftCount") or 0)
        unplanned_session_count = int(execution_insights.get("unplannedSessionCount") or 0)
        unplanned_easy_count = int(execution_insights.get("unplannedEasyCount") or 0)
        unplanned_hard_count = int(execution_insights.get("unplannedHardCount") or 0)
        quality_well_executed_count = int(execution_insights.get("qualityWellExecutedCount") or 0)
        recovery_too_hard_count = int(execution_insights.get("recoveryTooHardCount") or 0)
        long_run_too_hard_count = int(execution_insights.get("longRunTooHardCount") or 0)
        recent_7d = float(metrics.context.recent_7d_run_distance_km or 0.0)
        recent_30d = float(metrics.context.recent_30d_run_distance_km or 0.0)
        recent_count = int(metrics.context.recent_30d_run_count or 0)
        non_running_minutes = int(metrics.context.recent_7d_non_running_duration_minutes or 0)
        non_running_sessions = int(metrics.context.recent_7d_non_running_sessions or 0)
        baseline_weekly_km = max(recent_30d / 4.0, recent_7d, 12.0)
        block = cast(dict[str, Any], constraints.get("trainingBlock") or {})
        availability = cast(list[dict[str, Any]], constraints.get("availability") or [])
        availability_map = {
            int(item["weekday"]): item for item in availability if "weekday" in item
        }
        preferred_quality_days = [
            wd
            for wd, item in availability_map.items()
            if item.get("preferredSessionType") == "quality" and item.get("isAvailable", True)
        ]
        preferred_long_run_days = [
            wd
            for wd, item in availability_map.items()
            if item.get("preferredSessionType") == "long_run" and item.get("isAvailable", True)
        ]
        planning_notes: list[str] = []
        execution_adjustment_notes: list[str] = []
        pace_zones = PaceZoneEngine.calculate(metrics, race_config)
        strong_recovery_state = (
            readiness >= 70
            and fatigue <= 50
            and injury <= 25
            and active_injury_severity == 0
            and recovery_too_hard_count == 0
            and long_run_too_hard_count == 0
        )
        recent_key_session = (days_since_long_run is not None and days_since_long_run <= 1) or (
            days_since_quality is not None and days_since_quality <= 1
        )
        recovery_demand_days = 0
        if fatigue >= 80 or injury >= 60 or active_injury_severity >= 6:
            recovery_demand_days = 3
        elif fatigue >= 65 or injury >= 40 or readiness < 45:
            recovery_demand_days = 2
        elif recent_key_session and not strong_recovery_state:
            recovery_demand_days = 1
        if block.get("weeklyVolumeTargetKm") is not None:
            baseline_weekly_km = float(block["weeklyVolumeTargetKm"])
            planning_notes.append(
                f"{block['weeklyVolumeTargetKm']}km 주간 목표 블록을 기준으로 볼륨을 잡았습니다."
            )
        if non_running_minutes >= 180 or non_running_sessions >= 3:
            baseline_weekly_km *= 0.9
            planning_notes.append(
                "최근 자전거·등산 등 비러닝 부하를 반영해 러닝 볼륨을 보수적으로 조정했습니다."
            )
        if recovery_demand_days:
            baseline_weekly_km *= 0.92
            note = (
                f"최근 핵심 세션과 현재 회복 신호를 반영해 "
                f"초반 {recovery_demand_days}일은 회복 요구도를 우선했습니다."
            )
            planning_notes.append(note)
            execution_adjustment_notes.append(note)
        if reduced_stimulus_count >= 2:
            baseline_weekly_km *= 0.92
            note = "최근 계획보다 약한 자극으로 끝난 세션이 반복되어 이번 주 강도를 낮췄습니다."
            planning_notes.append(note)
            execution_adjustment_notes.append(note)
        if excessive_stimulus_count >= 2:
            baseline_weekly_km *= 0.9
            note = "최근 계획보다 강한 자극이 반복되어 회복 비중을 늘리고 볼륨을 감산했습니다."
            planning_notes.append(note)
            execution_adjustment_notes.append(note)

        if active_injury_severity >= 6:
            run_days = 3
            quality_count = 0
            volume_factor = 0.65
            planning_notes.append("활성 부상 강도가 높아 이번 주는 품질훈련을 제외했습니다.")
        elif fatigue >= 80 or injury >= 60 or readiness < 30:
            run_days = 4
            quality_count = 0
            volume_factor = 0.85
            planning_notes.append("피로도와 회복 상태를 고려해 이번 주는 강도 세션을 제외했습니다.")
        elif active_injury_severity >= 3 or fatigue >= 65 or injury >= 40 or readiness < 45:
            run_days = 4 if recent_count < 14 else 5
            quality_count = 1
            volume_factor = 0.9
            planning_notes.append("회복 여유가 크지 않아 강도와 볼륨을 보수적으로 제한했습니다.")
        elif readiness >= 70 and fatigue <= 45 and injury <= 25:
            run_days = 5 if recent_count < 22 else 6
            quality_count = 1
            volume_factor = 1.05
        else:
            run_days = 5 if recent_count < 20 else 6
            quality_count = 1
            volume_factor = 1.0
        if quality_well_executed_count >= 2 and readiness >= 60 and fatigue <= 50 and injury <= 30:
            volume_factor *= 1.03
            planning_notes.append(
                "최근 품질 세션의 실제 자극이 안정적으로 들어가 "
                "이번 주 구조를 크게 줄이지 않았습니다."
            )
        if non_running_minutes >= 240:
            quality_count = max(0, quality_count - 1)
            run_days = max(4, run_days - 1)
        if reduced_stimulus_count >= 2:
            quality_count = max(0, quality_count - 1)
        if excessive_stimulus_count >= 2:
            quality_count = max(0, quality_count - 1)
            run_days = max(4, run_days - 1)
        if unplanned_hard_count >= 1:
            quality_count = max(0, quality_count - 1)
            run_days = max(4, run_days - 1)
            note = (
                "최근 비계획 고강도 또는 장거리 세션이 있어 이번 주는 회복 우선으로 조정했습니다."
            )
            planning_notes.append(note)
            execution_adjustment_notes.append(note)
        elif unplanned_session_count >= 2:
            quality_count = max(0, quality_count - 1)
            note = "최근 비계획 세션이 누적되어 이번 주는 계획 단순성과 회복을 우선합니다."
            planning_notes.append(note)
            execution_adjustment_notes.append(note)
        elif unplanned_easy_count >= 2:
            note = "최근 비계획 easy/base 세션이 있어 주간 총량은 유지하되 강도 증가는 억제합니다."
            planning_notes.append(note)
            execution_adjustment_notes.append(note)
        if recovery_too_hard_count >= 1:
            quality_count = max(0, quality_count - 1)
            note = "최근 회복주가 너무 강해져 이번 주 easy/recovery 강도 통제를 더 강화합니다."
            planning_notes.append(note)
            execution_adjustment_notes.append(note)
        if long_run_too_hard_count >= 1:
            quality_count = max(0, quality_count - 1)
            note = (
                "최근 롱런 후반 강도가 과해 다음 long run은 "
                "길이와 후반 강도를 더 보수적으로 가져갑니다."
            )
            planning_notes.append(note)
            execution_adjustment_notes.append(note)

        target_weekly_km = baseline_weekly_km * volume_factor
        phase = str(block.get("phase") or "").lower()
        if phase == "base":
            quality_count = min(quality_count, 1)
            target_weekly_km *= 0.95
        elif phase == "build":
            target_weekly_km *= 1.0
        elif phase == "peak":
            run_days = max(run_days, 5)
            quality_count = 1
            target_weekly_km *= 0.9
        elif phase == "taper":
            quality_count = min(quality_count, 1)
            target_weekly_km *= 0.75
        if active_injury_severity >= 3:
            quality_count = 0
            target_weekly_km *= 0.85
            planning_notes.append("활성 통증이 있어 품질훈련보다 회복과 유지 주행을 우선했습니다.")
        long_run_minutes = self._minutes_from_distance(max(8.0, target_weekly_km * 0.3))
        base_minutes = self._minutes_from_distance(max(5.0, target_weekly_km * 0.16))
        recovery_minutes = max(25, base_minutes - 10)
        quality_minutes = max(base_minutes + 10, 45)
        if long_run_too_hard_count >= 1:
            long_run_minutes = max(60, int(long_run_minutes * 0.9))

        days = [{"date": (start_date + timedelta(days=index))} for index in range(7)]
        weekend_indexes = [i for i, day in enumerate(days) if day["date"].weekday() in {5, 6}]
        preferred_long_run_indexes = [
            i for i, day in enumerate(days) if day["date"].weekday() in preferred_long_run_days
        ]
        long_run_index = weekend_indexes[-1] if weekend_indexes else 6
        if recent_key_session and strong_recovery_state:
            note = (
                "최근 핵심 세션 이력이 있지만 회복·부하 신호가 안정적이라 "
                "주말 핵심 세션 배치를 허용했습니다."
            )
            planning_notes.append(note)
            execution_adjustment_notes.append(note)
        if preferred_long_run_indexes:
            long_run_index = preferred_long_run_indexes[0]
            planning_notes.append("주말 long run 선호를 반영했습니다.")
        quality_candidates = [
            i
            for i, day in enumerate(days)
            if day["date"].weekday() in {1, 2, 3} and abs(i - long_run_index) > 1
        ]
        preferred_quality_indexes = [
            i for i, day in enumerate(days) if day["date"].weekday() in preferred_quality_days
        ]
        if preferred_quality_indexes:
            quality_candidates = [
                i
                for i in preferred_quality_indexes
                if i in quality_candidates or abs(i - long_run_index) > 1
            ] or quality_candidates
            planning_notes.append("선호한 mid-week 품질훈련 요일을 우선 검토했습니다.")
        if schedule_shift_count >= 2 and preferred_quality_indexes:
            quality_candidates = sorted(
                quality_candidates,
                key=lambda i: (0 if i in preferred_quality_indexes else 1, i),
            )
            planning_notes.append("최근 일정 이동이 잦아 선호 요일 고정성을 더 높였습니다.")
        quality_index = quality_candidates[0] if quality_candidates and quality_count else None

        session_types = ["base"] * 7
        session_types[long_run_index] = "long_run"
        if quality_index is not None:
            session_types[quality_index] = "quality"

        # 불가 요일은 이미 강제 휴식이므로 추가 rest 배치 개수에서 차감
        forced_rest_count = sum(
            1
            for day in days
            if not availability_map.get(cast(Any, day["date"]).weekday(), {}).get(
                "isAvailable", True
            )
        )
        rest_days = max(0, 7 - run_days - forced_rest_count)
        recovery_pool = []
        if quality_index is not None:
            recovery_pool.extend(
                [index for index in (quality_index - 1, quality_index + 1) if 0 <= index < 7]
            )
        recovery_pool.extend(
            [index for index in (long_run_index - 1, long_run_index + 1) if 0 <= index < 7]
        )
        for index in recovery_pool:
            if session_types[index] == "base":
                session_types[index] = "recovery"

        for index in sorted(
            [i for i in range(7) if session_types[i] == "base"],
            key=lambda i: abs(i - long_run_index),
            reverse=True,
        )[:rest_days]:
            session_types[index] = "rest"

        for index, day in enumerate(days):
            weekday = cast(Any, day["date"]).weekday()
            rule = availability_map.get(weekday)
            if rule and not rule.get("isAvailable", True):
                session_types[index] = "rest"
                planning_notes.append(
                    f"{cast(Any, day['date']).isoformat()}은(는) 불가 요일로 휴식 배치했습니다."
                )

        if session_types[0] == "quality":
            session_types[1] = "recovery"

        for index in range(min(recovery_demand_days, len(session_types))):
            if session_types[index] in {"quality", "long_run"}:
                session_types[index] = "recovery" if recovery_demand_days == 1 else "rest"
            elif recovery_demand_days >= 2 and session_types[index] == "base":
                session_types[index] = "recovery"

        # quality 세션이 recovery_demand 로 제거됐다면, 원래 quality를 위해 잡아 뒀던
        # 인접 recovery 슬롯은 근거가 사라지므로 base로 되돌린다.
        # recovery_demand 기간(index < recovery_demand_days) 내 슬롯은 유지.
        if quality_index is not None and session_types[quality_index] in {"rest", "recovery"}:
            for adj in (quality_index - 1, quality_index + 1):
                if (
                    0 <= adj < 7
                    and adj >= recovery_demand_days
                    and session_types[adj] == "recovery"
                    and adj != long_run_index - 1
                    and adj != long_run_index + 1
                ):
                    session_types[adj] = "base"

        if recovery_demand_days and "long_run" not in session_types:
            later_long_run_candidates = [
                index
                for index in preferred_long_run_indexes + weekend_indexes
                if index >= recovery_demand_days
                and availability_map.get(days[index]["date"].weekday(), {}).get(
                    "isAvailable",
                    True,
                )
            ]
            if later_long_run_candidates:
                replacement_index = sorted(set(later_long_run_candidates))[0]
                session_types[replacement_index] = "long_run"
                planning_notes.append(
                    "초반 회복 요구도를 우선한 뒤 가능한 주말에 long run을 다시 배치했습니다."
                )

        skeleton = []
        for index, day in enumerate(days):
            session_type = session_types[index]
            date_value = cast(Any, day["date"]).isoformat()
            target_minutes = self._target_minutes_for_session(
                session_type=session_type,
                recovery_minutes=recovery_minutes,
                base_minutes=base_minutes,
                quality_minutes=quality_minutes,
                long_run_minutes=long_run_minutes,
            )
            weekday = cast(Any, day["date"]).weekday()
            rule = availability_map.get(weekday)
            max_duration_minutes = None
            if rule and rule.get("maxDurationMinutes") is not None:
                max_duration_minutes = int(rule["maxDurationMinutes"])
            if max_duration_minutes is not None and target_minutes > max_duration_minutes:
                target_minutes = max_duration_minutes
            workout_name, description_guide = self._session_metadata(
                session_type=session_type,
                race_config=race_config,
                target_minutes=target_minutes,
                notes=self._session_notes_for_day(
                    session_type=session_type,
                    day_index=index,
                    current_date=date_value,
                    quality_index=quality_index,
                    long_run_index=long_run_index,
                    planning_notes=planning_notes,
                    execution_adjustment_notes=execution_adjustment_notes,
                ),
            )
            skeleton.append(
                {
                    "date": date_value,
                    "sessionType": session_type,
                    "targetMinutes": target_minutes,
                    "workoutName": workout_name,
                    "descriptionGuide": description_guide,
                    "paceTargets": pace_zones.to_dict(),
                }
            )

        return skeleton

    @staticmethod
    def _minutes_from_distance(distance_km: float) -> int:
        """대략적인 러닝 시간 추정."""
        return int(round(distance_km * 6.2 * 5 / 5))

    @staticmethod
    def _target_minutes_for_session(
        session_type: str,
        recovery_minutes: int,
        base_minutes: int,
        quality_minutes: int,
        long_run_minutes: int,
    ) -> int:
        if session_type == "recovery":
            return recovery_minutes
        if session_type == "quality":
            return quality_minutes
        if session_type == "long_run":
            return long_run_minutes
        if session_type == "rest":
            return 0
        return base_minutes

    @staticmethod
    def _session_metadata(
        session_type: str,
        race_config: RaceConfig,
        target_minutes: int,
        notes: str = "",
    ) -> tuple[str, str]:
        if session_type == "recovery":
            return (
                "Recovery Run",
                (
                    f"회복 우선의 {target_minutes}분 러닝입니다. "
                    f"호흡과 자세를 편하게 유지하세요. {notes}"
                ).strip(),
            )
        if session_type == "quality":
            label = "Tempo Session" if race_config.has_goal else "Intervals"
            return (
                label,
                (
                    f"이번 주 핵심 품질훈련입니다. 총 {target_minutes}분 안에서 "
                    f"강도는 통제하세요. {notes}"
                ).strip(),
            )
        if session_type == "long_run":
            return (
                "Long Run",
                (
                    f"주말 장거리 러닝입니다. 총 {target_minutes}분을 "
                    f"안정적으로 소화하세요. {notes}"
                ).strip(),
            )
        if session_type == "rest":
            return (
                "Rest Day",
                f"회복과 적응을 위해 휴식을 우선합니다. {notes}".strip(),
            )
        return (
            "Base Run",
            f"기본 지구력 유지 목적의 {target_minutes}분 러닝입니다. {notes}".strip(),
        )

    @staticmethod
    def _session_notes_for_day(
        session_type: str,
        day_index: int,
        current_date: str,
        quality_index: Optional[int],
        long_run_index: int,
        planning_notes: list[str],
        execution_adjustment_notes: list[str],
    ) -> str:
        notes: list[str] = []
        unavailability_note = next(
            (note for note in planning_notes if "불가 요일" in note and current_date in note),
            "",
        )
        if session_type == "long_run" and day_index == long_run_index:
            notes.append("이번 주 long run 선호 요일을 반영했습니다.")
        if session_type == "quality" and quality_index is not None and day_index == quality_index:
            notes.append("회복 간격을 고려해 이번 주 핵심 세션을 배치했습니다.")
        if session_type in {"rest", "recovery"}:
            if unavailability_note:
                notes.append(unavailability_note)
            else:
                notes.extend(
                    note
                    for note in planning_notes
                    if (
                        ("회복" in note or "휴식" in note or "비러닝" in note)
                        and "불가 요일" not in note
                    )
                )
            if execution_adjustment_notes:
                notes.append(execution_adjustment_notes[0])
        elif session_type == "long_run":
            notes.extend(
                note for note in planning_notes if "long run" in note or "주간 목표" in note
            )
            notes.extend(
                note for note in execution_adjustment_notes if "장거리" in note or "회복" in note
            )
        elif session_type == "base":
            notes.extend(note for note in planning_notes if "비러닝" in note or "주간 목표" in note)
            adjustment_note = next(
                (note for note in execution_adjustment_notes if "비계획" in note or "회복" in note),
                "",
            )
            if adjustment_note:
                notes.append(adjustment_note)
        elif session_type == "quality":
            notes.extend(
                note
                for note in planning_notes
                if "품질훈련" in note or "품질 세션의 실제 자극" in note
            )
            adjustment_note = next(
                (
                    note
                    for note in execution_adjustment_notes
                    if "약한 자극" in note or "강한 자극" in note or "비계획 고강도" in note
                ),
                "",
            )
            if adjustment_note:
                notes.append(adjustment_note)
        return " ".join(dict.fromkeys(note for note in notes if note)).strip()

    @staticmethod
    def _pace_for_step(
        pace_zones: dict[str, str],
        step_type: str,
        session_type: str,
    ) -> str:
        if step_type == "Warmup":
            return pace_zones.get("warmup", "6:45")
        if step_type == "Cooldown":
            return pace_zones.get("cooldown", "7:10")
        if step_type == "Recovery":
            return pace_zones.get("recovery", "7:20")
        if step_type == "Interval":
            return pace_zones.get("interval", "4:30")
        if session_type == "recovery":
            return pace_zones.get("recovery", "7:20")
        if session_type == "long_run":
            return pace_zones.get("longRun", "6:40")
        if session_type == "quality":
            return pace_zones.get("tempo", "5:15")
        return pace_zones.get("base", "6:45")

    @staticmethod
    def _step(
        step_type: str,
        duration_seconds: int,
        target_type: str = "no_target",
        target_value: str = "0:00",
    ) -> dict[str, Any]:
        return {
            "type": step_type,
            "durationValue": max(duration_seconds, 1),
            "durationUnit": "second",
            "targetType": target_type,
            "targetValue": target_value,
        }
