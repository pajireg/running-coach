"""템플릿 기반 한국어 운동 설명 생성 — LLM 없음.

Free tier 에서 LLM 대신 상태 기반 phrase 조합으로 description 을 만든다.
LLM 의 fluid 한 문장과 달리 간결하고 일관적이며 결정론적이다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ...coaching.context import CoachingContext

_BASE: dict[str, str] = {
    "rest": (
        "오늘은 훈련 자극을 더하지 않고 회복을 완성하는 날입니다. "
        "근육과 결합조직이 적응할 시간을 주면 다음 러닝의 품질이 좋아집니다. "
        "가벼운 걷기나 스트레칭 정도만 하고 피로를 남기지 마세요."
    ),
    "recovery": (
        "오늘은 피로를 풀면서 다리 순환을 살리는 회복주입니다. "
        "낮은 강도는 회복을 방해하지 않으면서 훈련 리듬과 유산소 기반을 유지해 줍니다. "
        "대화가 편한 페이스로 끝까지 가볍게 마무리하세요."
    ),
    "base": (
        "오늘은 편안한 유산소 자극을 쌓는 베이스 러닝입니다. "
        "꾸준한 저강도 주행은 심폐 효율과 지방 대사, 후반 페이스 유지 능력을 키웁니다. "
        "속도를 증명하려 하지 말고 호흡이 안정적인 범위에 머무르세요."
    ),
    "long_run": (
        "오늘은 현재 계획 범위에서 지구력의 중심이 되는 장거리 러닝입니다. "
        "긴 시간 움직이며 글리코겐 사용 효율과 피로 저항력, 후반 집중력이 좋아집니다. "
        "초반을 여유 있게 시작하고 마지막까지 자세가 무너지지 않게 유지하세요."
    ),
    "quality_interval": (
        "오늘은 짧은 빠른 구간으로 상한 속도와 산소 이용 능력을 자극합니다. "
        "인터벌은 VO2max와 빠른 페이스에서의 주법 경제성을 끌어올리는 데 도움이 됩니다. "
        "각 반복을 전력질주가 아니라 통제 가능한 빠른 리듬으로 끝내세요."
    ),
    "quality_threshold": (
        "오늘은 버겁지만 지속 가능한 강도로 젖산 역치를 밀어 올리는 세션입니다. "
        "역치 능력이 좋아지면 목표 페이스를 더 오래 유지하고 후반 급격한 둔화를 줄일 수 있습니다. "
        "호흡은 깊지만 무너지지 않는 수준으로 일정하게 가져가세요."
    ),
    "quality_tempo": (
        "오늘은 목표 페이스에 가까운 지속 자극으로 리듬과 지속력을 다지는 세션입니다. "
        "템포 러닝은 빠른 속도를 오래 견디는 근지구력과 페이스 감각을 개선합니다. "
        "초반 과속을 피하고 후반에도 같은 리듬을 재현하는 데 집중하세요."
    ),
    "quality_fartlek": (
        "오늘은 빠르고 느린 구간을 섞어 부담을 낮추면서 변화 대응력을 키우는 세션입니다. "
        "파틀렉은 신경근 반응, 페이스 전환 능력, 회복 중 재가속 감각을 개선합니다. "
        "빠른 구간은 날카롭게, 느린 구간은 확실히 회복되게 달리세요."
    ),
    "quality": (
        "오늘은 현재 상태에서 필요한 핵심 능력을 자극하는 품질 세션입니다. "
        "목표 강도 안에서 달리면 속도 지속력과 러닝 경제성이 좋아집니다. "
        "정해진 페이스 범위를 넘기지 말고 마지막 반복까지 자세를 유지하세요."
    ),
}

# (조건 함수, 추가 문장) — 첫 번째로 매칭되는 것 하나만 사용
_MODIFIERS: list[tuple] = [
    (
        lambda c: c.active_injury.is_active and c.active_injury.severity >= 3,
        "부상 회복 중이라 오늘의 목적은 자극보다 안전한 적응입니다.",
    ),
    (
        lambda c: c.scores.readiness < 40,
        "회복도가 낮아 오늘은 강도보다 컨디션 회복을 우선했습니다.",
    ),
    (
        lambda c: c.scores.fatigue > 70,
        "피로 누적이 높아 훈련 효과보다 과부하 방지를 우선했습니다.",
    ),
    (
        lambda c: c.training_block is not None and c.training_block.phase == "taper",
        "대회가 임박했기 때문에 새 피로를 만들기보다 컨디션을 끌어올리는 쪽에 맞췄습니다.",
    ),
    (
        lambda c: c.training_block is not None and c.training_block.phase == "peak",
        "훈련 최고조 단계라 필요한 핵심 자극은 유지하되 회복 여지를 남깁니다.",
    ),
]

_QUALITY_NAME_TO_SUBTYPE = {
    "Interval": "interval",
    "Threshold": "threshold",
    "Tempo Run": "tempo",
    "Fartlek": "fartlek",
}

_ADAPTATION_TERMS = (
    "좋아",
    "키웁",
    "올리",
    "개선",
    "유지",
    "회복",
    "강화",
    "효율",
    "저항력",
    "역치",
    "VO2max",
)

_FORBIDDEN_ROLLING_HORIZON_FRAMING = (
    "금주",
    "이번 주",
    "주간",
    "이번 주 훈련을 마무리",
    "주간 훈련을 마무리",
    "훈련을 마무리하며",
    "한 주를 마무리",
    "다음 주 강도",
    "다음 주 훈련",
    "다음 주를 준비",
    "next week",
    "end of the week",
)


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

    @staticmethod
    def quality_subtype_from_workout_name(workout_name: str | None) -> Optional[str]:
        """Canonical workout name 에서 quality subtype 추론."""
        if not workout_name:
            return None
        return _QUALITY_NAME_TO_SUBTYPE.get(workout_name)

    @staticmethod
    def needs_expansion(description: str | None) -> bool:
        """LLM 설명이 짧거나 rolling horizon 맥락과 어긋나면 보강 대상."""
        text = (description or "").strip()
        lowered = text.lower()
        if any(term.lower() in lowered for term in _FORBIDDEN_ROLLING_HORIZON_FRAMING):
            return True
        if len(text) < 55:
            return True
        return not any(term in text for term in _ADAPTATION_TERMS)
