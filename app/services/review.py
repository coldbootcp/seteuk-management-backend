"""Reviewer — 생성된 추천을 그대로 학생에게 내보내지 않는다.

통합 결정 P-3: *"생성된 추천은 후보다. 검수 단계가 근거 없는·반복되는·안전하지 않은
출력을 걸러낼 수 있어야 한다."*

검사는 두 종류다.

- **결정론적 검사**가 보증한다 — 서로 사실상 같은 후보, 이미 세운 계획과 겹치는 후보,
  단정적·위험한 표현. 프롬프트로도 같은 것을 부탁하지만, 실제 DeepSeek이 그 지시를
  무시하는 것을 지식 그래프와 챗봇에서 이미 두 번 관측했다. 프롬프트는 부탁이고
  코드가 보증이다.
- **탈락시키되 지우지 않는다** — 어떤 후보가 왜 걸렸는지 `flags`로 남겨, 나중에
  루브릭을 조정할 때 근거로 쓴다.
"""

import re
from dataclasses import dataclass, field

from app.services.korean_text import similarity as _similarity

# 학생에게 확신을 심어 주면 안 되는 표현. 입시 결과·건강·진단은 이 서비스가 단정할
# 수 있는 영역이 아니다.
_UNSAFE_PATTERNS = [
    ("입시 결과 단정", re.compile(r"합격(을)?\s*(보장|확정)|반드시\s*합격|100%\s*(합격|성공)")),
    (
        "대학 지정 단정",
        re.compile(
            r"(서울대|연세대|고려대|카이스트|KAIST)\s*(에)?\s*(합격|진학)(할 수 있|한다|이 가능)"
        ),
    ),
    ("의학적 단정", re.compile(r"(치료|완치|진단)(할 수 있|된다|이 가능)")),
    ("등급 단정", re.compile(r"\d\s*등급(을)?\s*(보장|확정|만들어)")),
]

# 제목이 이 비율 이상 겹치면 표현만 다른 같은 주제로 본다.
_DUPLICATE_RATIO = 0.6


@dataclass
class OptionReview:
    index: int
    passed: bool = True
    flags: list[str] = field(default_factory=list)

    def fail(self, reason: str) -> None:
        self.passed = False
        self.flags.append(reason)


def review_options(
    options: list[dict], existing_plan_titles: list[str] | None = None
) -> list[OptionReview]:
    """후보 목록을 검수한다. 반환은 후보와 같은 순서·길이다."""
    existing = existing_plan_titles or []
    reviews = [OptionReview(index=index) for index in range(len(options))]

    for index, option in enumerate(options):
        topic = str(option.get("topic", ""))
        blob = " ".join(str(v) for v in option.values() if isinstance(v, str))

        if not topic.strip():
            reviews[index].fail("주제가 비어 있음")

        for label, pattern in _UNSAFE_PATTERNS:
            if pattern.search(blob):
                reviews[index].fail(f"안전하지 않은 단정: {label}")

        # 이미 세운 계획과 겹치면 새 제안이 아니다. 챗봇이 같은 계획을 두 번 만든
        # 사고와 같은 부류다.
        for title in existing:
            if _similarity(topic, title) >= _DUPLICATE_RATIO:
                reviews[index].fail(f"이미 있는 계획과 사실상 동일: {title}")
                break

    # 후보끼리의 중복 — 뒤에 오는 것을 떨어뜨려 첫 번째는 남긴다.
    for index in range(len(options)):
        if not reviews[index].passed:
            continue
        for earlier in range(index):
            if not reviews[earlier].passed:
                continue
            if _similarity(
                str(options[index].get("topic", "")), str(options[earlier].get("topic", ""))
            ) >= _DUPLICATE_RATIO:
                reviews[index].fail("다른 후보와 표현만 다른 같은 주제")
                break

    return reviews
