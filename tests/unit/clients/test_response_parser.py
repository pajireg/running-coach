import pytest

from running_coach.clients.gemini.response_parser import parse_gemini_json
from running_coach.exceptions import GeminiResponseParseError


def test_parse_gemini_json_strips_markdown_fence():
    parsed = parse_gemini_json(
        """
        ```json
        {"plan": [{"date": "2026-04-22"}]}
        ```
        """
    )

    assert parsed == {"plan": [{"date": "2026-04-22"}]}


def test_parse_gemini_json_raises_domain_error_for_invalid_json():
    with pytest.raises(GeminiResponseParseError):
        parse_gemini_json("{not valid json")
