"""LLM 설정 모델."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

PlannerMode = Literal["legacy", "llm_driven"]
LLMProvider = Literal["gemini", "openai", "anthropic"]


class LLMSettings(BaseModel):
    """실제 planner 호출에 적용되는 LLM 설정."""

    planner_mode: PlannerMode = Field(default="legacy", alias="plannerMode")
    llm_provider: LLMProvider = Field(default="gemini", alias="llmProvider")
    llm_model: str = Field(alias="llmModel")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("llm_model")
    @classmethod
    def validate_model_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("llm_model must not be empty")
        return normalized


class UserLLMSettings(BaseModel):
    """사용자 override 와 fallback 적용 결과."""

    user_id: str
    override_planner_mode: Optional[PlannerMode] = None
    override_llm_provider: Optional[LLMProvider] = None
    override_llm_model: Optional[str] = None
    effective: LLMSettings

    model_config = ConfigDict(populate_by_name=True)


class AdminLLMSettingsPatch(BaseModel):
    """관리자 global LLM 설정 수정 요청."""

    planner_mode: Optional[PlannerMode] = Field(default=None, alias="plannerMode")
    llm_provider: Optional[LLMProvider] = Field(default=None, alias="llmProvider")
    llm_model: Optional[str] = Field(default=None, alias="llmModel")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("llm_model")
    @classmethod
    def validate_optional_model_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("llm_model must not be empty")
        return normalized


class UserLLMSettingsPatch(BaseModel):
    """사용자별 LLM override 수정 요청.

    필드를 null 로 보내면 override 를 해제한다.
    """

    planner_mode: Optional[PlannerMode] = Field(default=None, alias="plannerMode")
    llm_provider: Optional[LLMProvider] = Field(default=None, alias="llmProvider")
    llm_model: Optional[str] = Field(default=None, alias="llmModel")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("llm_model")
    @classmethod
    def validate_optional_model_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("llm_model must not be empty")
        return normalized
