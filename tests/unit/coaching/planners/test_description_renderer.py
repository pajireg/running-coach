"""DescriptionRenderer 설명 품질 테스트."""

from __future__ import annotations

from types import SimpleNamespace

from running_coach.coaching.planners.description_renderer import DescriptionRenderer


def _ctx():
    return SimpleNamespace(
        active_injury=SimpleNamespace(is_active=False, severity=0),
        scores=SimpleNamespace(readiness=70, fatigue=40),
        training_block=SimpleNamespace(phase="build"),
    )


def test_base_description_explains_reason_adaptation_and_execution():
    description = DescriptionRenderer.render("base", None, _ctx())

    assert "베이스 러닝" in description
    assert "심폐 효율" in description
    assert "호흡" in description
    assert not DescriptionRenderer.needs_expansion(description)


def test_short_description_needs_expansion():
    assert DescriptionRenderer.needs_expansion("유산소 기초 다지기")


def test_quality_subtype_from_workout_name():
    assert DescriptionRenderer.quality_subtype_from_workout_name("Threshold") == "threshold"
