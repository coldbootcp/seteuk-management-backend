"""한국어 텍스트 비교 유틸.

한국어는 교착어라 조사·어미가 붙으면 같은 말이 다른 토큰이 된다 — "모델"과 "모델의",
"검증"과 "검증하기", "분석"과 "분석해". 토큰을 정확히 일치시키는 방식은 영어에서는
그럭저럭 동작하지만 여기서는 겹침을 거의 못 잡는다.

정합 판정과 추천 검수가 둘 다 이 문제를 만나서, 각자 다르게 풀지 않도록 한곳에 모았다.
형태소 분석기를 붙이면 더 정확하겠지만 무거운 의존이 하나 늘고, 지금 필요한 것은
"같은 말인지 대충 아는 것"이라 접두사 비교로 충분하다.
"""

import re

_TOKEN_SPLIT = re.compile(r"[^가-힣a-zA-Z0-9]+")
MIN_TOKEN_LENGTH = 2


def tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_SPLIT.split(text) if len(t) >= MIN_TOKEN_LENGTH}


def _same_word(left: str, right: str) -> bool:
    """한쪽이 다른 쪽의 접두사면 같은 말로 본다."""
    return left.startswith(right) or right.startswith(left)


def overlap_count(text: str, reference: str) -> int:
    """`reference`의 어휘 중 몇 개가 `text`에 나타나는지."""
    text_tokens = tokens(text)
    return sum(
        1
        for token in tokens(reference)
        if any(_same_word(other, token) for other in text_tokens)
    )


def similarity(left: str, right: str) -> float:
    """두 문구가 얼마나 같은 말인지(0~1).

    작은 쪽을 기준으로 재는 이유는, 짧은 제목이 긴 제목 안에 통째로 들어가는 경우도
    사실상 같은 주제이기 때문이다.
    """
    a, b = tokens(left), tokens(right)
    if not a or not b:
        return 0.0
    matched = sum(1 for token in a if any(_same_word(other, token) for other in b))
    return matched / min(len(a), len(b))
