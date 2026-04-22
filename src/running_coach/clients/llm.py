"""LLM provider JSON 호출 adapter."""

from __future__ import annotations

import json
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..exceptions import LLMProviderError, LLMProviderResponseParseError


class JSONLLMClient(Protocol):
    """Prompt 를 JSON dict 응답으로 변환하는 provider 공통 인터페이스."""

    provider: str
    model: str

    def invoke_json(self, prompt: str) -> dict[str, Any]:
        """LLM 호출 후 JSON dict 반환."""


class OpenAIResponsesJSONClient:
    """OpenAI Responses API JSON adapter."""

    provider = "openai"
    endpoint = "https://api.openai.com/v1/responses"

    def __init__(self, api_key: str, model: str, timeout_seconds: int = 120):
        if not api_key:
            raise LLMProviderError("Missing OpenAI API key")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def invoke_json(self, prompt: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "input": f"{prompt}\n\nReturn only valid JSON.",
            "text": {"format": {"type": "json_object"}},
            "store": False,
        }
        response = _post_json(
            url=self.endpoint,
            headers={"Authorization": f"Bearer {self.api_key}"},
            payload=payload,
            timeout_seconds=self.timeout_seconds,
        )
        raw_text = _extract_openai_text(response)
        return _parse_json_text(raw_text, provider="OpenAI")


class AnthropicMessagesJSONClient:
    """Anthropic Messages API JSON adapter."""

    provider = "anthropic"
    endpoint = "https://api.anthropic.com/v1/messages"
    api_version = "2023-06-01"

    def __init__(self, api_key: str, model: str, timeout_seconds: int = 120):
        if not api_key:
            raise LLMProviderError("Missing Anthropic API key")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def invoke_json(self, prompt: str) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "max_tokens": 8192,
            "messages": [
                {
                    "role": "user",
                    "content": f"{prompt}\n\nReturn only valid JSON.",
                }
            ],
        }
        response = _post_json(
            url=self.endpoint,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": self.api_version,
            },
            payload=payload,
            timeout_seconds=self.timeout_seconds,
        )
        raw_text = _extract_anthropic_text(response)
        return _parse_json_text(raw_text, provider="Anthropic")


def _post_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    request = Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8")
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise LLMProviderError(f"LLM provider HTTP {exc.code}: {error_body}") from exc
    except URLError as exc:
        raise LLMProviderError(f"LLM provider network error: {exc}") from exc

    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise LLMProviderResponseParseError("LLM provider returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise LLMProviderResponseParseError("LLM provider response is not an object")
    return parsed


def _extract_openai_text(response: dict[str, Any]) -> str:
    output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text:
        return output_text

    for item in response.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str) and text:
                return text
    raise LLMProviderResponseParseError("OpenAI response did not include output text")


def _extract_anthropic_text(response: dict[str, Any]) -> str:
    for content in response.get("content", []):
        if not isinstance(content, dict):
            continue
        text = content.get("text")
        if isinstance(text, str) and text:
            return text
    raise LLMProviderResponseParseError("Anthropic response did not include output text")


def _parse_json_text(raw_text: str, provider: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise LLMProviderResponseParseError(f"{provider} output was not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise LLMProviderResponseParseError(f"{provider} output was not a JSON object")
    return parsed
