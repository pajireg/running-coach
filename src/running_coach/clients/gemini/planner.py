"""훈련 계획 생성기"""

import json
import re
import time
from datetime import timedelta
from typing import Any, Optional, cast

from google import genai
from google.genai import types

from ...config.constants import GEMINI_MODEL, WORKOUT_PREFIX
from ...exceptions import GeminiQuotaExceededError, GeminiResponseParseError
from ...models.config import RaceConfig
from ...models.metrics import AdvancedMetrics
from ...models.training import TrainingPlan
from ...utils.logger import get_logger
from ...utils.retry import retry_on_quota_exceeded

logger = get_logger(__name__)


class TrainingPlanner:
    """훈련 계획 생성기"""

    def __init__(self, gemini_client: genai.Client):
        """
        Args:
            gemini_client: genai.Client 인스턴스
        """
        self.client = gemini_client

    @retry_on_quota_exceeded(max_attempts=3)
    def generate_plan(
        self,
        metrics: AdvancedMetrics,
        race_config: RaceConfig,
        include_strength: bool = False,
        training_background: Optional[dict[str, Any]] = None,
    ) -> Optional[TrainingPlan]:
        """훈련 계획 생성"

        Args:
            metrics: AdvancedMetrics 모델
            race_config: RaceConfig 모델
            include_strength: 근력 운동 포함 여부

        Returns:
            TrainingPlan 모델 또는 None
        """
        logger.info("Gemini로 7일 훈련 계획 생성 중...")
        weekly_skeleton = self._build_weekly_skeleton(metrics, race_config, training_background)

        # 프롬프트 생성
        prompt = self._build_prompt(
            metrics,
            race_config,
            include_strength,
            training_background,
            weekly_skeleton,
        )
        # logger.info("prompt:\n", prompt)

        # API 호출 및 재시도
        for attempt in range(3):
            try:
                response = self.client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json"),
                )

                # JSON 파싱
                plan_json = self._parse_response(response.text or "")
                plan_json = self._normalize_plan_json(plan_json, metrics, weekly_skeleton)

                # Pydantic 모델로 변환
                return TrainingPlan(**plan_json)

            except Exception as e:
                if "429" in str(e):
                    logger.warning(f"API 할당량 초과. 45초 후 재시도... ({attempt+1}/3)")
                    raise GeminiQuotaExceededError("API quota exceeded") from e
                else:
                    logger.error(f"Gemini API 에러: {e}")
                    if attempt == 2:
                        fallback = self._fallback_plan_json(metrics, weekly_skeleton)
                        return TrainingPlan(**fallback)
                    logger.info(f"재시도 중... ({attempt+1}/3)")
                    time.sleep(2)

        return None

    def _build_prompt(
        self,
        metrics: AdvancedMetrics,
        race_config: RaceConfig,
        include_strength: bool,
        training_background: Optional[dict[str, Any]],
        weekly_skeleton: list[dict[str, Any]],
    ) -> str:
        """프롬프트 생성"""
        metrics_dict = metrics.to_gemini_dict()

        race_info = ""
        if race_config.has_goal:
            race_info += f"- RACE DATE: {race_config.date}\n" if race_config.date else ""
            race_info += (
                f"- RACE DISTANCE: {race_config.distance}\n" if race_config.distance else ""
            )
            race_info += f"- GOAL TIME: {race_config.goal_time}\n" if race_config.goal_time else ""
            race_info += (
                f"- TARGET PACE: {race_config.target_pace}\n" if race_config.target_pace else ""
            )
        else:
            race_info = "- No specific race date.\n- Focus on overall fitness."

        strength_rule = (
            "Mention optional strength advice only in the Korean description. "
            "Do not output strength sessions as workouts or steps."
            if include_strength
            else "STRICTLY RUNNING ONLY. Use 'Rest' for non-running days."
        )

        periodization_rule = ""
        if race_config.has_goal and race_config.date:
            periodization_rule = (
                f"If a race is set: Calculate weeks until race. "
                f"Adjust total weekly volume and long run distance based on "
                f"RACE DISTANCE ({race_config.distance}) and proximity to RACE DATE."
            )
        else:
            periodization_rule = (
                "Maintain a balanced mix of base runs, recovery, and one hard session."
            )

        pace_rule = ""
        if race_config.goal_time and race_config.distance:
            pace_rule = (
                f"- If GOAL TIME ({race_config.goal_time}) is set for "
                f"DISTANCE ({race_config.distance}), calculate the required target pace. "
                f"Use this pace for race-specific intervals."
            )

        health_json = json.dumps(metrics_dict["health"], ensure_ascii=False)
        performance_json = json.dumps(metrics_dict["performance"], ensure_ascii=False)
        context_json = json.dumps(metrics_dict["context"], ensure_ascii=False)
        background_json = json.dumps(training_background or {}, ensure_ascii=False)
        skeleton_json = json.dumps(weekly_skeleton, ensure_ascii=False)

        prompt_lines = [
            "You are an elite running coach.",
            f"Create a 7-day training plan starting today ({metrics.date}).",
            "",
            "USER DATA:",
            f"- Recent Health: {health_json}",
            f"- Performance: {performance_json}",
            (
                "- Performance includes PRs, VO2Max, Lactate Threshold, "
                "and Max Heart Rate when available."
            ),
            f"- Context (Yesterday Actual vs Planned): {context_json}",
            f"- Long-Term Training Background: {background_json}",
            f"- Weekly Skeleton (must preserve): {skeleton_json}",
            "",
            "RACE CONTEXT:",
            race_info.strip(),
            "",
            "COACHING RULES:",
            "1. ADAPTIVE PLANNING:",
            "   - Use 'yesterday_actual' to adapt today and the rest of the week.",
            "   - Use the long-term background to avoid overreaching beyond proven volume.",
            "   - If the athlete skipped or added work, do not blindly stack intensity.",
            "   - If load is high and HRV is low, prioritize recovery or rest.",
            (
                "   - The weekly skeleton is mandatory. Preserve session type, "
                "date, and overall structure."
            ),
            "2. SPORT TYPE:",
            "   - ONLY RUNNING workouts are allowed.",
            f"   - {strength_rule}",
            "3. PERIODIZATION & VOLUME:",
            f"   - {periodization_rule}",
            "   - Respect recent training load and avoid sudden volume spikes.",
            "4. PACE & TARGETS:",
            f"   {pace_rule}".rstrip(),
            "   - Calculate training zones from PRs and Lactate Threshold.",
            "   - Use 'speed' only when a concrete pace is appropriate.",
            "   - targetValue must be plain MM:SS only.",
            "5. Weekend: exactly one Long Run on Saturday or Sunday.",
            "6. Mid-week: one Interval or Tempo session.",
            "7. STRUCTURE CONTROL:",
            "   - Keep exactly the 7 skeleton dates in the same order.",
            "   - Keep the provided workoutName for each day.",
            "   - Keep total duration close to the skeleton's targetMinutes.",
            "7. RATIONALE:",
            "   - Put a brief Korean rationale in 'description'.",
            "   - Tie it to the race goal or general fitness.",
            "8. SESSION CONTENT:",
            "   - For rest days, return an empty steps array.",
            "   - For recovery/base/long days, mostly use Warmup, Run, Cooldown.",
            "   - For quality days, use Warmup, Interval, Recovery, Cooldown or a tempo-style Run.",
            "9. SAFETY:",
            "   - No doubles and no zero-duration steps.",
            "   - Avoid back-to-back quality sessions.",
            "   - If data is sparse, stay conservative.",
            "",
            "OUTPUT FORMAT:",
            "Return ONLY valid JSON with key 'plan' and 7 days.",
            "Each day must be:",
            "{",
            '  "date": "YYYY-MM-DD",',
            '  "workout": {',
            f'    "workoutName": "{WORKOUT_PREFIX}: [Day Type]",',
            '    "description": "Short explanation in Korean",',
            '    "sportType": "RUNNING",',
            '    "steps": [',
            "      {",
            '        "type": "Warmup|Run|Interval|Recovery|Cooldown",',
            '        "durationValue": 1800,',
            '        "durationUnit": "second",',
            '        "targetType": "no_target|speed",',
            '        "targetValue": "MM:SS"',
            "      }",
            "    ]",
            "  }",
            "}",
        ]
        return "\n".join(line for line in prompt_lines if line != "")

    def _normalize_plan_json(
        self,
        plan_json: dict[str, Any],
        metrics: AdvancedMetrics,
        weekly_skeleton: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """모델 출력을 업로드 가능한 형태로 정규화"""
        normalized_days = []
        raw_days = plan_json.get("plan", [])
        start_date = metrics.date
        skeleton = weekly_skeleton or self._build_weekly_skeleton(metrics, RaceConfig(), None)

        for index, skeleton_day in enumerate(skeleton[:7]):
            item = raw_days[index] if index < len(raw_days) else {}
            workout = item.get("workout", {})
            steps = []

            for step in workout.get("steps", []):
                target_type = step.get("targetType") or "no_target"
                target_value = step.get("targetValue") or "0:00"
                if isinstance(target_value, str):
                    target_value = target_value.replace("/km", "").strip()

                if target_type == "speed" and not re.fullmatch(r"\d+:\d{2}", target_value):
                    target_type = "no_target"
                    target_value = "0:00"

                steps.append(
                    {
                        "type": step.get("type", "Run"),
                        "durationValue": max(int(step.get("durationValue", 0) or 0), 1),
                        "durationUnit": "second",
                        "targetType": target_type,
                        "targetValue": target_value,
                    }
                )

            if self._should_replace_steps(steps, skeleton_day):
                steps = self._default_steps_for_skeleton_day(skeleton_day)

            normalized_days.append(
                {
                    "date": skeleton_day.get(
                        "date",
                        (start_date + timedelta(days=index)).isoformat(),
                    ),
                    "workout": {
                        "workoutName": skeleton_day.get(
                            "workoutName",
                            workout.get("workoutName", f"{WORKOUT_PREFIX}: Day {index + 1}"),
                        ),
                        "description": workout.get(
                            "description",
                            skeleton_day.get("descriptionGuide", ""),
                        ),
                        "sportType": "RUNNING",
                        "steps": steps,
                    },
                }
            )

        return {"plan": normalized_days}

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
        active_injury = cast(dict[str, Any], state.get("activeInjury") or {})
        active_injury_severity = int(active_injury.get("severity") or 0)
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
        if non_running_minutes >= 240:
            quality_count = max(0, quality_count - 1)
            run_days = max(4, run_days - 1)

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

        days = [{"date": (start_date + timedelta(days=index))} for index in range(7)]
        weekend_indexes = [i for i, day in enumerate(days) if day["date"].weekday() in {5, 6}]
        preferred_long_run_indexes = [
            i for i, day in enumerate(days) if day["date"].weekday() in preferred_long_run_days
        ]
        long_run_index = weekend_indexes[-1] if weekend_indexes else 6
        if preferred_long_run_indexes:
            long_run_index = preferred_long_run_indexes[0]
            planning_notes.append("주말 long run 선호를 반영했습니다.")
        quality_candidates = [
            i
            for i, day in enumerate(days)
            if day["date"].weekday() in {1, 2, 3}
            and abs(i - long_run_index) > 1
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
        quality_index = quality_candidates[0] if quality_candidates and quality_count else None

        session_types = ["base"] * 7
        session_types[long_run_index] = "long_run"
        if quality_index is not None:
            session_types[quality_index] = "quality"

        rest_days = max(1, 7 - run_days)
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
                    quality_index=quality_index,
                    long_run_index=long_run_index,
                    planning_notes=planning_notes,
                ),
            )
            skeleton.append(
                {
                    "date": date_value,
                    "sessionType": session_type,
                    "targetMinutes": target_minutes,
                    "workoutName": workout_name,
                    "descriptionGuide": description_guide,
                }
            )

        return skeleton

    def _fallback_plan_json(
        self, metrics: AdvancedMetrics, weekly_skeleton: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """LLM 실패 시 규칙 기반 conservative plan 생성."""
        return self._normalize_plan_json({"plan": []}, metrics, weekly_skeleton)

    def _parse_response(self, text: str) -> dict[str, Any]:
        """JSON 응답 파싱"""
        try:
            # 1. 마크다운 블록 제거
            if "```json" in text:
                text = text.split("```json")[-1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[-1].split("```")[0].strip()

            # 2. 제어 문자 및 잘못된 이스케이프 정제
            text = text.replace("\n", " ").replace("\r", "")

            # 유효하지 않은 이스케이프 제거
            text = re.sub(r'\\(?![ux"\\\/bfnrt])', r"", text)

            # 3. JSON 파싱
            return cast(dict[str, Any], json.loads(text.strip()))

        except json.JSONDecodeError as e:
            logger.error(f"JSON 파싱 실패 (위치: {e.pos}): {e.msg}")
            start = max(0, e.pos - 40)
            end = min(len(text), e.pos + 40)
            logger.error(f"에러 주변 컨텍스트: ...{text[start:end]}...")
            raise GeminiResponseParseError(f"Failed to parse JSON response: {e}") from e

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
                f"{WORKOUT_PREFIX}: Recovery Run",
                (
                    f"회복 우선의 {target_minutes}분 러닝입니다. "
                    f"호흡과 자세를 편하게 유지하세요. {notes}"
                ).strip(),
            )
        if session_type == "quality":
            label = "Tempo Session" if race_config.has_goal else "Intervals"
            return (
                f"{WORKOUT_PREFIX}: {label}",
                (
                    f"이번 주 핵심 품질훈련입니다. 총 {target_minutes}분 안에서 "
                    f"강도는 통제하세요. {notes}"
                ).strip(),
            )
        if session_type == "long_run":
            return (
                f"{WORKOUT_PREFIX}: Long Run",
                (
                    f"주말 장거리 러닝입니다. 총 {target_minutes}분을 "
                    f"안정적으로 소화하세요. {notes}"
                ).strip(),
            )
        if session_type == "rest":
            return (
                f"{WORKOUT_PREFIX}: Rest Day",
                f"회복과 적응을 위해 휴식을 우선합니다. {notes}".strip(),
            )
        return (
            f"{WORKOUT_PREFIX}: Base Run",
            f"기본 지구력 유지 목적의 {target_minutes}분 러닝입니다. {notes}".strip(),
        )

    @staticmethod
    def _session_notes_for_day(
        session_type: str,
        day_index: int,
        quality_index: Optional[int],
        long_run_index: int,
        planning_notes: list[str],
    ) -> str:
        notes: list[str] = []
        if session_type == "long_run" and day_index == long_run_index:
            notes.append("이번 주 long run 선호 요일을 반영했습니다.")
        if session_type == "quality" and quality_index is not None and day_index == quality_index:
            notes.append("회복 간격을 고려해 이번 주 핵심 세션을 배치했습니다.")
        if session_type in {"rest", "recovery"}:
            notes.extend(
                note
                for note in planning_notes
                if "회복" in note or "휴식" in note or "불가 요일" in note or "비러닝" in note
            )
        elif session_type == "long_run":
            notes.extend(
                note for note in planning_notes if "long run" in note or "주간 목표" in note
            )
        elif session_type == "base":
            notes.extend(note for note in planning_notes if "비러닝" in note or "주간 목표" in note)
        elif session_type == "quality":
            notes.extend(note for note in planning_notes if "품질훈련" in note)
        return " ".join(dict.fromkeys(note for note in notes if note)).strip()

    def _should_replace_steps(
        self, steps: list[dict[str, Any]], skeleton_day: dict[str, Any]
    ) -> bool:
        session_type = skeleton_day.get("sessionType")
        target_minutes = int(skeleton_day.get("targetMinutes") or 0)
        if session_type == "rest":
            return True
        if not steps:
            return True
        total_seconds = sum(int(step.get("durationValue", 0) or 0) for step in steps)
        if total_seconds <= 0:
            return True
        if target_minutes <= 0:
            return False
        target_seconds = target_minutes * 60
        return total_seconds < target_seconds * 0.6 or total_seconds > target_seconds * 1.4

    def _default_steps_for_skeleton_day(self, skeleton_day: dict[str, Any]) -> list[dict[str, Any]]:
        session_type = str(skeleton_day.get("sessionType") or "base")
        target_seconds = int(skeleton_day.get("targetMinutes") or 0) * 60
        if session_type == "rest":
            return []
        if session_type == "recovery":
            return [
                self._step("Warmup", 300),
                self._step("Run", max(target_seconds - 600, 900)),
                self._step("Cooldown", 300),
            ]
        if session_type == "quality":
            quality_block = max(target_seconds - 1500, 1200)
            repeat = max(3, min(6, quality_block // 360))
            interval_seconds = max(180, quality_block // (repeat * 2))
            steps = [self._step("Warmup", 900)]
            for _ in range(repeat):
                steps.append(self._step("Interval", interval_seconds, target_type="speed"))
                steps.append(self._step("Recovery", interval_seconds))
            steps.append(self._step("Cooldown", 600))
            return steps
        if session_type == "long_run":
            return [
                self._step("Warmup", 600),
                self._step("Run", max(target_seconds - 900, 2700)),
                self._step("Cooldown", 300),
            ]
        return [
            self._step("Warmup", 600),
            self._step("Run", max(target_seconds - 900, 1800)),
            self._step("Cooldown", 300),
        ]

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
