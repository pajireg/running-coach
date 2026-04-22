"""Gemini structured JSON 응답 파서.

마크다운 블록과 제어 문자를 정제한 뒤 json.loads 로 dict 반환.
LLM planner 계층에서 공통으로 사용한다.
"""

import json
import re
from typing import Any, cast

from ...exceptions import GeminiResponseParseError
from ...utils.logger import get_logger

logger = get_logger(__name__)


def parse_gemini_json(raw_text: str) -> dict[str, Any]:
    """Gemini structured JSON 응답 → dict."""
    text = raw_text
    try:
        if "```json" in text:
            text = text.split("```json")[-1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[-1].split("```")[0].strip()

        text = text.replace("\n", " ").replace("\r", "")
        text = re.sub(r'\\(?![ux"\\\/bfnrt])', r"", text)

        return cast(dict[str, Any], json.loads(text.strip()))

    except json.JSONDecodeError as e:
        logger.error(f"JSON 파싱 실패 (위치: {e.pos}): {e.msg}")
        start = max(0, e.pos - 40)
        end = min(len(text), e.pos + 40)
        logger.error(f"에러 주변 컨텍스트: ...{text[start:end]}...")
        raise GeminiResponseParseError(f"Failed to parse JSON response: {e}") from e
