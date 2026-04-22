"""LLM provider adapter 테스트."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from running_coach.clients.gemini.client import GeminiJSONClient
from running_coach.clients.llm import AnthropicMessagesJSONClient, OpenAIResponsesJSONClient


def test_gemini_adapter_uses_configured_model():
    client = MagicMock()
    response = MagicMock()
    response.text = json.dumps({"ok": True})
    client.models.generate_content.return_value = response

    result = GeminiJSONClient(client=client, model="gemini-custom").invoke_json("prompt")

    assert result == {"ok": True}
    assert client.models.generate_content.call_args.kwargs["model"] == "gemini-custom"


def test_openai_adapter_posts_to_responses_api_and_extracts_output_text():
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(
        {"output": [{"content": [{"text": '{"ok": true}'}]}]}
    ).encode("utf-8")

    with patch("running_coach.clients.llm.urlopen", return_value=response) as urlopen:
        result = OpenAIResponsesJSONClient(api_key="key", model="gpt-test").invoke_json("prompt")

    request = urlopen.call_args.args[0]
    payload = json.loads(request.data.decode("utf-8"))
    assert result == {"ok": True}
    assert request.full_url == "https://api.openai.com/v1/responses"
    assert request.headers["Authorization"] == "Bearer key"
    assert payload["model"] == "gpt-test"
    assert payload["text"]["format"]["type"] == "json_object"


def test_anthropic_adapter_posts_to_messages_api_and_extracts_text():
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(
        {"content": [{"type": "text", "text": '{"ok": true}'}]}
    ).encode("utf-8")

    with patch("running_coach.clients.llm.urlopen", return_value=response) as urlopen:
        result = AnthropicMessagesJSONClient(api_key="key", model="claude-test").invoke_json(
            "prompt"
        )

    request = urlopen.call_args.args[0]
    payload = json.loads(request.data.decode("utf-8"))
    assert result == {"ok": True}
    assert request.full_url == "https://api.anthropic.com/v1/messages"
    assert request.headers["X-api-key"] == "key"
    assert request.headers["Anthropic-version"] == "2023-06-01"
    assert payload["model"] == "claude-test"
