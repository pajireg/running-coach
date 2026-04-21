"""템플릿 기반 한국어 운동 설명 생성 — LLM 없음.

Free tier 에서 LLM 대신 상태 기반 phrase 조합으로 description 을 만든다.
LLM 의 fluid 한 문장과 달리 간결하고 일관적이며 결정론적이다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ...coaching.context import CoachingContext

_BASE: dict[str, str] = {
    "rest": "완전 휴식일입니다. 가벼운 스트레칭만 권장합니다.",
    "recovery": "피로 회복을 위한 짧고 편안한 러닝입니다.",
    "base": "유산소 기초 체력을 다지는 편안한 페이스 주행입니다.",
    "long_run": "지구력과 피로 저항력 향상을 위한 장거리 주행입니다.",
    "quality_interval": "VO2max 향상을 위한 짧은 고강도 인터벌 세션입니다.",
    "quality_threshold": "젖산 역치 향상을 위한 역치 페이스 지속주입니다.",
    "quality_tempo": "지속력 강화를 위한 템포 페이스 중장시간 주행입니다.",
    "quality_fartlek": "변속 적응을 위한 불규칙 강도 파틀렉 세션입니다.",
}

# (조건 함수, 추가 문장) — 첫 번째로 매칭되는 것 하나만 사용
_MODIFIERS: list[tuple] = [
    (
        lambda c: c.active_injury.is_active and c.active_injury.severity >= 3,
        "부상 회복 중임을 고려해 볼륨을 제한했습니다.",
    ),
    (
        lambda c: c.scores.readiness < 40,
        "회복이 부족한 상태를 고려해 강도를 최소화했습니다.",
    ),
    (
        lambda c: c.scores.fatigue > 70,
        "피로 누적이 높아 보수적 부하를 유지합니다.",
    ),
    (
        lambda c: c.training_block is not None and c.training_block.phase == "taper",
        "대회가 임박해 강도를 낮췄습니다.",
    ),
    (
        lambda c: c.training_block is not None and c.training_block.phase == "peak",
        "훈련 최고조 단계로 핵심 자극을 유지합니다.",
    ),
]


class DescriptionRenderer:
    """session_type + 컨텍스트 → 한국어 운동 설명."""

    @staticmethod
    def render(
        session_type: str,
        quality_subtype: Optional[str],
        ctx: "CoachingContext",
    ) -> str:
        key = (
            f"quality_{quality_subtype}"
            if session_type == "quality" and quality_subtype
            else session_type
        )
        base = _BASE.get(key) or _BASE.get(session_type, "훈련 세션입니다.")

        for check, msg in _MODIFIERS:
            try:
                if check(ctx):
                    return f"{base} {msg}"
            except Exception:
                pass

        return base
