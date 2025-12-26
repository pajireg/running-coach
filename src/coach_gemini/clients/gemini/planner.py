"""훈련 계획 생성기"""
import json
import re
import time
from typing import Optional
from google import genai
from google.genai import types
from ...models.metrics import AdvancedMetrics
from ...models.config import RaceConfig
from ...models.training import TrainingPlan
from ...config.constants import GEMINI_MODEL
from ...utils.logger import get_logger
from ...exceptions import GeminiError, GeminiQuotaExceededError, GeminiResponseParseError
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
        include_strength: bool = False
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

        # 프롬프트 생성
        prompt = self._build_prompt(metrics, race_config, include_strength)
        # logger.info("prompt:\n", prompt)

        # API 호출 및 재시도
        for attempt in range(3):
            try:
                response = self.client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json")
                )

                # JSON 파싱
                plan_json = self._parse_response(response.text)

                # Pydantic 모델로 변환
                return TrainingPlan(**plan_json)

            except Exception as e:
                if "429" in str(e):
                    logger.warning(f"API 할당량 초과. 45초 후 재시도... ({attempt+1}/3)")
                    raise GeminiQuotaExceededError("API quota exceeded") from e
                else:
                    logger.error(f"Gemini API 에러: {e}")
                    if attempt == 2:
                        return None
                    logger.info(f"재시도 중... ({attempt+1}/3)")
                    time.sleep(2)

        return None

    def _build_prompt(
        self,
        metrics: AdvancedMetrics,
        race_config: RaceConfig,
        include_strength: bool
    ) -> str:
        """프롬프트 생성"""
        metrics_dict = metrics.to_gemini_dict()

        race_info = ""
        if race_config.has_goal:
            race_info += f"- RACE DATE: {race_config.date}\n" if race_config.date else ""
            race_info += f"- RACE DISTANCE: {race_config.distance}\n" if race_config.distance else ""
            race_info += f"- GOAL TIME: {race_config.goal_time}\n" if race_config.goal_time else ""
            race_info += f"- TARGET PACE: {race_config.target_pace}\n" if race_config.target_pace else ""
        else:
            race_info = "- No specific race date.\n- Focus on overall fitness."

        strength_rule = (
            "Include strength training only if it complements the running plan."
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
            periodization_rule = "Maintain a balanced mix of base runs, recovery, and one hard session."

        pace_rule = ""
        if race_config.goal_time and race_config.distance:
            pace_rule = (
                f"- If GOAL TIME ({race_config.goal_time}) is set for "
                f"DISTANCE ({race_config.distance}), calculate the required target pace. "
                f"Use this pace for race-specific intervals."
            )

        prompt = f"""
You are an elite running coach. Based on the user's Garmin data, create a **7-day training plan** starting today ({metrics.date}).

USER DATA:
- Recent Health: {json.dumps(metrics_dict['health'], ensure_ascii=False)}
- Performance: {json.dumps(metrics_dict['performance'], ensure_ascii=False)} (includes PRs, VO2Max, Lactate Threshold, and optionally Max Heart Rate if provided)
- Context (Yesterday Actual vs Planned): {json.dumps(metrics_dict['context'], ensure_ascii=False)}

RACE CONTEXT:
{race_info}

COACHING RULES:
1. ADAPTIVE PLANNING:
   - Look at 'yesterday_actual' in context. If the user skipped a planned workout or did extra, adjust TODAY and the rest of the week accordingly.
   - If they are over-trained (high load, low HRV), prioritize recovery/rest.
2. SPORT TYPE:
   - **ONLY RUNNING workouts are allowed.**
   - {strength_rule}
3. PERIODIZATION & VOLUME:
   - {periodization_rule}
4. PACE & TARGETS:
   {pace_rule}
   - Calculate training zones based on PRs and Lactate Threshold.
   - Use 'speed' target type for runs.
5. Weekend: One "Long Run" (Saturday or Sunday).
6. Mid-week: One "Interval" or "Tempo" session.
7. RATIONALE (Korean): For each workout, provide a brief rationale in Korean in the 'description' field, explaining how it helps with the specific RACE GOAL or general fitness.

OUTPUT FORMAT:
Return a JSON object with a key 'plan' containing a list of 7 days.
Each day should have:
{{
  "date": "YYYY-MM-DD",
  "workout": {{
    "workoutName": "Coach Gemini: [Day Type]",
    "description": "Short explanation in Korean",
    "sportType": "RUNNING",
    "steps": [
      {{
        "type": "Warmup|Run|Interval|Recovery|Cooldown",
        "durationValue": 1800,
        "durationUnit": "second",
        "targetType": "no_target|speed",
        "targetValue": "MM:SS"
      }}
    ]
  }}
}}

Return ONLY valid JSON.
"""
        return prompt

    def _parse_response(self, text: str) -> dict:
        """JSON 응답 파싱"""
        try:
            # 1. 마크다운 블록 제거
            if "```json" in text:
                text = text.split("```json")[-1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[-1].split("```")[0].strip()

            # 2. 제어 문자 및 잘못된 이스케이프 정제
            text = text.replace('\n', ' ').replace('\r', '')

            # 유효하지 않은 이스케이프 제거
            text = re.sub(r'\\(?![ux"\\\/bfnrt])', r'', text)

            # 3. JSON 파싱
            return json.loads(text.strip())

        except json.JSONDecodeError as e:
            logger.error(f"JSON 파싱 실패 (위치: {e.pos}): {e.msg}")
            start = max(0, e.pos - 40)
            end = min(len(text), e.pos + 40)
            logger.error(f"에러 주변 컨텍스트: ...{text[start:end]}...")
            raise GeminiResponseParseError(f"Failed to parse JSON response: {e}") from e
