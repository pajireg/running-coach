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


def test_calendar_week_closure_description_needs_expansion():
    stale = (
        "금주 훈련을 마무리하며 가볍게 몸을 풀어주는 베이스 런입니다. "
        "체력을 과도하게 소진하지 않으면서 달리기 리듬을 유지하는 것이 핵심입니다. "
        "가벼운 발걸음으로 주간 훈련을 성공적으로 마친다는 느낌으로 마무리하세요."
    )
    assert DescriptionRenderer.needs_expansion(stale)


def test_calendar_week_core_session_description_needs_expansion():
    stale = (
        "지구력과 피로 저항력을 향상시키기 위한 이번 주 핵심 장거리 훈련입니다. "
        "꾸준한 페이스를 유지하며 목표 완주를 위한 기초 체력을 다집니다. "
        "중간에 급격한 페이스 변화 없이 일정한 리듬을 유지하세요."
    )
    assert DescriptionRenderer.needs_expansion(stale)


def test_weekly_mileage_description_needs_expansion():
    stale = (
        "템포런의 피로를 정리하고 주간 총 마일리지를 채우기 위한 회복형 베이스 러닝입니다. "
        "가벼운 움직임을 통해 젖산을 분산시키고 신체 리듬을 유지합니다. "
        "발의 피로도를 점검하며 가볍게 발을 굴리듯 수행하세요."
    )
    assert DescriptionRenderer.needs_expansion(stale)


def test_quality_subtype_from_workout_name():
    assert DescriptionRenderer.quality_subtype_from_workout_name("Threshold") == "threshold"
