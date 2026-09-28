"""과목 내용 요약 — 상담 챗봇이 과목과 주제를 이을 때 기댈 근거.

과목 카탈로그(`subject_catalog`)에는 이름·교과군·선택 구분만 있다. 그것만 주면 챗봇은
"이 과목에서 무엇을 배우는가"를 모델의 일반 지식으로 채우는데, 2022 개정에서 새로 생기거나
재편된 과목(대수, 미적분Ⅰ, 역학과 에너지 등)은 2015 과목 내용과 섞거나 없는 단원을
지어낼 수 있다. 그래서 공식 교육과정 문서에서 과목마다 한두 문장 소개와 단원(내용 영역)
이름을 옮겨 두고, 상담 컨텍스트의 이번 학기 수강 과목에 함께 싣는다.

데이터는 `subject_contents/*.json`(교육과정·묶음별)에 두고 카탈로그 코드(`2022:대수`)로
찾는다. 카탈로그와 같은 이유로 DB가 아니라 코드 저장소에 둔다 — 교육과정 고시가 바뀔
때만 바뀌는 참조 데이터다. 요약이 없는 과목은 None을 돌려주고, 상담 프롬프트는 그런
과목의 단원 내용을 단정하지 않게 한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from app.services.subject_catalog import get_subject

_DATA_DIR = Path(__file__).with_name("subject_contents")


@dataclass(frozen=True)
class SubjectContent:
    summary: str  # 과목이 무엇을 다루는지 1~2문장
    units: tuple[str, ...]  # 공식 내용 체계의 영역·단원 이름
    source: str  # 옮겨 온 문서


@cache
def _contents() -> dict[str, SubjectContent]:
    contents: dict[str, SubjectContent] = {}
    for path in sorted(_DATA_DIR.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        source = raw["source"]
        for code, entry in raw["subjects"].items():
            if get_subject(code) is None:
                raise ValueError(f"{path.name}: 카탈로그에 없는 과목 코드 {code!r}")
            if code in contents:
                raise ValueError(f"{path.name}: {code!r}가 다른 파일에도 있다")
            contents[code] = SubjectContent(
                summary=entry["summary"].strip(),
                units=tuple(u.strip() for u in entry["units"]),
                source=entry.get("source", source),
            )
    return contents


def get_content(code: str | None) -> SubjectContent | None:
    if code is None:
        return None
    return _contents().get(code)


def covered_codes() -> set[str]:
    return set(_contents())
