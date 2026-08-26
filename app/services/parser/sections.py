import re

# Official 생기부 exports frequently letter-space section headers for justification
# (e.g. "3. 출 결 상 황" instead of "3. 출결상황"), and the spacing is inconsistent even
# within the same document. Each canonical header therefore matches with optional
# whitespace tolerated between every character, not just after the leading "N.".
_CANONICAL_NAMES = [
    "인적사항",
    "학적사항",
    "출결상황",
    "수상경력",
    "진로희망사항",
    "창의적체험활동상황",
    "동아리활동",
    "봉사활동실적",
    "교과학습발달상황",
    "독서활동상황",
    "행동특성 및 종합의견",
]


def _spaced(literal: str) -> str:
    return r"\s*".join(re.escape(ch) for ch in literal)


_NAME_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (name, re.compile(r"^\d+\.\s*" + _spaced(name) + r"\s*$", re.MULTILINE))
    for name in _CANONICAL_NAMES
]
# 자격증 취득 현황 섹션은 문서마다 부제가 달라("자격증 및 인증 취득상황" 등) 접두어만 고정한다.
_NAME_PATTERNS.append(
    ("자격증", re.compile(r"^\d+\.\s*" + _spaced("자격증") + r".*$", re.MULTILINE))
)


def split_sections(text: str) -> dict[str, str]:
    matches: list[tuple[str, re.Match[str]]] = []
    for name, pattern in _NAME_PATTERNS:
        match = pattern.search(text)
        if match:
            matches.append((name, match))

    matches.sort(key=lambda pair: pair[1].start())

    sections: dict[str, str] = {}
    for i, (name, match) in enumerate(matches):
        start = match.end()
        end = matches[i + 1][1].start() if i + 1 < len(matches) else len(text)
        sections[name] = text[start:end].strip()
    return sections
