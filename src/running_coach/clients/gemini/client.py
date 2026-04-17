"""Gemini AI 클라이언트"""

from typing import Any, Optional, cast

from google import genai

from ...exceptions import GeminiError
from ...models.config import RaceConfig
from ...models.metrics import AdvancedMetrics
from ...models.training import TrainingPlan
from ...utils.logger import get_logger
from .planner import TrainingPlanner

logger = get_logger(__name__)


class GeminiClient:
    """Gemini AI 클라이언트"""

    def __init__(self, api_key: str):
        """
        Args:
            api_key: Gemini API 키
        """
        if not api_key:
            raise GeminiError("Missing Gemini API key")

        self.api_key = api_key
        self.client = genai.Client(api_key=api_key)
        self.planner: TrainingPlanner = TrainingPlanner(self.client)

    def create_training_plan(
        self,
        metrics: AdvancedMetrics,
        race_config: RaceConfig,
        include_strength: bool = False,
        training_background: Optional[dict[str, Any]] = None,
    ) -> Optional[TrainingPlan]:
        """훈련 계획 생성

        Args:
            metrics: AdvancedMetrics 모델
            race_config: RaceConfig 모델
            include_strength: 근력 운동 포함 여부

        Returns:
            TrainingPlan 모델 또는 None
        """
        return cast(
            Optional[TrainingPlan],
            self.planner.generate_plan(
                metrics,
                race_config,
                include_strength,
                training_background=training_background,
            ),
        )
