"""GeminiClient 디스패처: mode 에 따라 올바른 sub-planner 호출."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from running_coach.clients.gemini.client import GeminiClient
from running_coach.coaching.context import CoachingContextBuilder
from running_coach.coaching.safety import DEFAULT_SAFETY_RULES, SafetyValidator
from running_coach.exceptions import GeminiError
from running_coach.models.config import RaceConfig
from running_coach.models.context import ActivityContext
from running_coach.models.health import HealthMetrics
from running_coach.models.metrics import AdvancedMetrics
from running_coach.models.performance import PerformanceMetrics


def _metrics() -> AdvancedMetrics:
    return AdvancedMetrics(
        date=date(2026, 4, 20),
        health=HealthMetrics(),
        performance=PerformanceMetrics(),
        context=ActivityContext(),
    )


@pytest.fixture
def fake_genai_client():
    """genai.Client 생성을 bypass."""
    with patch("running_coach.clients.gemini.client.genai.Client") as mock:
        instance = MagicMock()
        mock.return_value = instance
        yield instance


@pytest.fixture
def deps():
    """GeminiClient 에 필요한 context_builder + safety_validator."""
    history = MagicMock()
    history.summarize_training_background.return_value = {}
    history.list_recent_completed_activities.return_value = []
    return {
        "context_builder": CoachingContextBuilder(history_service=history),
        "safety_validator": SafetyValidator(rules=list(DEFAULT_SAFETY_RULES)),
    }


class TestGeminiClientDispatch:
    def test_default_mode_is_legacy(self, fake_genai_client, deps):
        client = GeminiClient(api_key="x", **deps)
        assert client.mode == "legacy"

    def test_both_modes_require_dependencies(self, fake_genai_client):
        # legacy 와 llm_driven 모두 context_builder + safety_validator 필요
        with pytest.raises(GeminiError, match="context_builder"):
            GeminiClient(api_key="x", mode="legacy")

    def test_llm_driven_mode_constructs_with_dependencies(self, fake_genai_client, deps):
        client = GeminiClient(api_key="x", mode="llm_driven", model="gemini-custom", **deps)
        assert client.mode == "llm_driven"
        assert client.model == "gemini-custom"

    def test_legacy_mode_invokes_legacy_planner(self, fake_genai_client, deps):
        client = GeminiClient(api_key="x", mode="legacy", **deps)
        with patch.object(client._legacy, "generate_plan", return_value=None) as legacy_call:
            client.create_training_plan(
                metrics=_metrics(),
                race_config=RaceConfig(),
                replan_reasons=["x"],
            )
            legacy_call.assert_called_once()

    def test_llm_driven_mode_invokes_llm_planner(self, fake_genai_client, deps):
        client = GeminiClient(api_key="x", mode="llm_driven", **deps)
        with patch.object(client._llm, "generate_plan", return_value=None) as llm_call:
            client.create_training_plan(
                metrics=_metrics(),
                race_config=RaceConfig(),
                replan_reasons=["x"],
            )
            llm_call.assert_called_once()

    def test_missing_api_key_raises(self):
        with pytest.raises(GeminiError, match="API key"):
            GeminiClient(api_key="")
