"""학적사항에서 입학 시점을 읽는다.

날짜만 있고 학년이 없는 기록(수상이 대표적이다)에 학년을 붙이려면 "이 학생이 몇
학년도에 1학년이었는가"라는 기준점이 필요하다. 그 답은 학적사항에 그대로 적혀 있다.

    2018년 3월 5일  가온고등학교  제1학년 입학

추론이 아니라 문서가 밝힌 사실이므로, 다른 곳에서 학년을 되짚는 것보다 이쪽을
먼저 본다.
"""

import re

from app.services.academic_year import academic_year_of
from app.services.parser.dates import normalize_date

# "2018년 3월 5일 ... 제1학년 입학" — 학교 이름이 사이에 끼므로 사이를 느슨하게 둔다.
_ENROLLMENT_PATTERN = re.compile(
    r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일[^\n]{0,40}?제\s*1\s*학년\s*입학"
)


def parse_freshman_academic_year(section_text: str) -> int | None:
    """1학년이었던 학년도. 학적사항에 입학 기록이 없으면 None.

    3월 입학이 보통이지만 편입·재입학처럼 다른 달일 수도 있어서, 날짜를 그대로
    학년도로 옮긴다(1~2월은 앞 학년도에 속한다).
    """
    match = _ENROLLMENT_PATTERN.search(section_text)
    if match is None:
        return None
    enrolled = normalize_date(f"{match.group(1)}.{match.group(2)}.{match.group(3)}.")
    return None if enrolled is None else academic_year_of(enrolled)
