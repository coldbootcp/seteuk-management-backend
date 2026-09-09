import re

from app.schemas.seteuk import AcademicPerformanceItem
from app.services.parser.anchors import (
    GRADE_HEADER_PATTERN,
    SEMESTER_LABEL_PATTERN,
    nearest_preceding,
)

GRADE_ROW_PATTERN = re.compile(
    r"(?P<subject>[가-힣A-Za-z0-9Ⅰ-Ⅳ·]+)[ \t]+"
    r"(?P<units>\d+)[ \t]+"
    r"(?P<raw_score>\d+(?:\.\d+)?)[ \t]*/[ \t]*(?P<subject_average>\d+(?:\.\d+)?)[ \t]*"
    r"\((?P<std_deviation>\d+(?:\.\d+)?)\)[ \t]+"
    r"(?P<achievement_grade>[A-E])\((?P<student_count>\d+)\)"
    # Same-line only — \s would let this optional group swallow the next line's
    # leading digit (e.g. a following "2학기" label), see test coverage.
    r"(?:[ \t]+(?P<rank>\d+(?:\.\d+)?))?"
)

SUBJECT_CATEGORY_PREFIXES: list[tuple[str, str]] = [
    ("국어", "국어"),
    ("수학", "수학"),
    ("영어", "영어"),
    ("한국사", "사회"),
    ("통합사회", "사회"),
    ("사회", "사회"),
    ("역사", "사회"),
    ("도덕", "사회"),
    ("통합과학", "과학"),
    ("과학", "과학"),
    ("체육", "체육"),
    ("음악", "예술"),
    ("미술", "예술"),
    ("기술", "기술·가정"),
    ("가정", "기술·가정"),
    ("정보", "기술·가정"),
    ("한문", "한문"),
    ("중국어", "제2외국어"),
    ("일본어", "제2외국어"),
    ("독일어", "제2외국어"),
    ("프랑스어", "제2외국어"),
    ("스페인어", "제2외국어"),
]


def infer_category(subject: str) -> str:
    for prefix, category in SUBJECT_CATEGORY_PREFIXES:
        if subject.startswith(prefix):
            return category
    return subject


# --- Table-cell reconstruction (parse_academic_performance, below) turned out to be
# unsound for this document format: pdfplumber packs several subjects into one cell as
# newline-joined text, but a subject's NAME can independently wrap onto an extra line
# too (e.g. "사회(역사/도\n덕포함)"), so a matching line-count between the 과목 and 교과
# cells does not guarantee the lines are actually aligned to the same subject.
#
# This second implementation instead walks PyMuPDF's linear (non-table) text for the
# whole 교과학습발달상황 section: it finds each "단위수 원점수/평균(표준편차) 성취도(인원)
# 석차등급" score tuple first (a shape that cannot span a subject boundary), then reads
# the subject/category name from the text *between* consecutive tuples. In testing
# against a real sample export this recovered far more rows (58 score tuples vs. 10)
# than the table-based approach, so it is the primary path; parse_academic_performance
# stays as a fallback for exports that render this section as PARSER_SPEC.md describes
# ("[N학년]" bracket headers over free-standing score lines) rather than a real table.
# 등급 과목(A~E)과 P(합격/불합격) 과목은 열 구성 자체가 다르다. 등급 과목은
# "성취도(수강자수) 석차등급"까지 네 칸이 다 있지만, P 과목은 석차가 존재하지
# 않는 개념이라 이 문서에서는 그 칸이 아예 비어 있다(글자조차 없음). rank를
# 항상 필수로 두면, P 과목 뒤에 그 칸이 없으니 정규식이 바로 다음 과목의
# 단위수 숫자를 이 과목의 석차로 잘못 삼켜 버린다 — 실제로 "보건" 다음
# "공학 일반"의 이름과 단위수가 이렇게 통째로 씹혔다. 그래서 두 모양을 아예
# 다른 갈래로 나눈다: 등급 과목만 석차를 필수로 요구하고, P 과목은 그 자리에서
# 매칭을 끝내 뒤따르는 글자를 절대 건드리지 않는다.
SCORE_TUPLE_PATTERN = re.compile(
    r"(?P<units>\d+)\s+"
    r"(?P<score>P|\d+/\d+\.\d+(?:\(\d+\.\d+\))?)\s+"
    r"(?:"
    r"(?P<achievement>[A-E])\((?P<student_count>\d+)\)\s+(?P<rank>[1-9]|·)"
    r"|"
    r"(?P<achievement_p>P)"
    r")"
)

_KNOWN_CATEGORIES = [
    "사회(역사/도덕포함)",
    "기술·가정/제2외국어/한문/교양",
    "체육·예술",
    "국어",
    "수학",
    "영어",
    "과학",
    "사회",
    "체육",
    "예술",
    "기술·가정",
    "교양",
]

_HEADER_NOISE = [
    "교과",
    "과목",
    "1학기",
    "2학기",
    "비고",
    "단위수",
    "단위",
    "원점수/과목평균",
    "(표준편차)",
    "(수강자수)",
    "(이수자수)",
    "석차등급",
    "석차",
    "등급",
    "원점수",
    "과목평균",
]

# Word-wrap points observed in this specific export's category names — collapsing all
# whitespace to single spaces (below) turns a wrap into a stray space in a fixed spot.
_WRAP_FIXUPS = [
    ("사회(역사/도 덕포함)", "사회(역사/도덕포함)"),
    ("기술·가정/제 2외국어/한문/ 교양", "기술·가정/제2외국어/한문/교양"),
    ("기술·가정/제 2외국어/한문/교양", "기술·가정/제2외국어/한문/교양"),
]

_IGNORED_SUBJECTS = {"", "이수단위", "합계", "교과", "과목", "단위"}


def _prefix_to_category_and_subject(prefix: str) -> tuple[str, str]:
    # The same document can mix U+30FB (katakana middle dot) and U+00B7 (real middle
    # dot) for "·" in "기술·가정" depending on which embedded font subset rendered it.
    prefix = prefix.replace("・", "·")
    prefix = GRADE_HEADER_PATTERN.sub(" ", prefix)
    prefix = re.sub(r"^.*?석차\s*등급", " ", prefix, flags=re.DOTALL)
    prefix = re.sub(r"^.*?성취도", " ", prefix, flags=re.DOTALL)
    for noise in _HEADER_NOISE:
        prefix = prefix.replace(noise, " ")
    prefix = re.sub(r"\s+", " ", prefix).strip()
    for wrapped, fixed in _WRAP_FIXUPS:
        prefix = prefix.replace(wrapped, fixed)

    for category in _KNOWN_CATEGORIES:
        if prefix.startswith(category):
            remainder = prefix[len(category) :].strip()
            return category, (remainder or category)

    words = prefix.split()
    if len(words) >= 2:
        return words[0], " ".join(words[1:])
    if words:
        return words[0], words[0]
    return "", ""


def parse_academic_performance_from_text(section_text: str) -> list[AcademicPerformanceItem]:
    clean_text = re.sub(r"\s+", " ", section_text).strip()
    grade_headers = list(GRADE_HEADER_PATTERN.finditer(clean_text))

    def grade_at(pos: int) -> int:
        anchor = nearest_preceding(grade_headers, pos)
        return int(anchor.group(1)) if anchor else 1

    matches = list(SCORE_TUPLE_PATTERN.finditer(clean_text))
    items: list[AcademicPerformanceItem] = []

    i = 0
    last_end = 0
    while i < len(matches):
        current = matches[i]
        next_match = matches[i + 1] if i + 1 < len(matches) else None
        # 같은 과목의 1·2학기가 나란히 있으면 그 사이에는 과목명이 다시 나오지
        # 않는다 — 숫자 열이 바로 이어 붙는다. 예전에는 "글자 수가 15자 미만이면
        # 같은 과목"으로 판단했는데, 다음 과목의 이름이 짧으면(예: "문학" 2글자 +
        # 교과 "국어" 2글자) 그 15자 문턱을 넘지 못해 서로 다른 두 과목이 하나로
        # 합쳐졌다 — 실제 생기부에서 "문학", "수학Ⅱ", "영어Ⅰ", "물리학Ⅰ"이 이렇게
        # 통째로 사라지고 그 값이 앞 과목의 2학기 성적으로 잘못 붙었다. 사이에
        # 글자(과목명)가 조금이라도 있으면 다른 과목이다 — 없어야만 같은 과목이다.
        gap_text = clean_text[current.end() : next_match.start()] if next_match else ""
        is_same_subject_next_semester = next_match is not None and gap_text.strip() == ""

        prefix = clean_text[last_end : current.start()]
        category, subject = _prefix_to_category_and_subject(prefix)
        grade = grade_at(current.start())

        if subject in _IGNORED_SUBJECTS:
            last_end = current.end()
            i += 1
            continue

        items.append(_build_item(grade, 1, category, subject, current))

        if is_same_subject_next_semester and next_match is not None:
            items.append(_build_item(grade, 2, category, subject, next_match))
            last_end = next_match.end()
            i += 2
            continue

        last_end = current.end()
        i += 1

    return items


def _build_item(
    grade: int, semester: int, category: str, subject: str, match: re.Match[str]
) -> AcademicPerformanceItem:
    score = match["score"]
    raw_score = subject_average = std_deviation = None
    if score != "P":
        score_match = re.match(r"(\d+)/(\d+(?:\.\d+)?)\((\d+(?:\.\d+)?)\)", score)
        if score_match:
            raw_score = float(score_match.group(1))
            subject_average = float(score_match.group(2))
            std_deviation = float(score_match.group(3))

    achievement_grade = match["achievement"] or match["achievement_p"]
    student_count = int(match["student_count"]) if match["student_count"] else None
    rank = match["rank"]

    return AcademicPerformanceItem(
        grade=grade,
        semester=semester,
        category=category or infer_category(subject),
        subject=subject,
        units=int(match["units"]),
        achievement_grade=achievement_grade,
        student_count=student_count,
        raw_score=raw_score,
        subject_average=subject_average,
        std_deviation=std_deviation,
        rank=None if rank in (None, "·") else rank,
    )


def extract_subject_names_from_text(section_text: str) -> list[str]:
    clean_text = re.sub(r"\s+", " ", section_text).strip()
    matches = list(SCORE_TUPLE_PATTERN.finditer(clean_text))

    subjects: set[str] = set()
    last_end = 0
    for match in matches:
        _, subject = _prefix_to_category_and_subject(clean_text[last_end : match.start()])
        if subject not in _IGNORED_SUBJECTS:
            subjects.add(subject)
        last_end = match.end()

    return sorted(subjects)


def parse_academic_performance(section_text: str) -> list[AcademicPerformanceItem]:
    """Fallback for the "[N학년] 과목 단위수 원점수/평균(표준편차) 성취도(인원) 석차등급"
    single-line layout docs/PARSER_SPEC.md describes — see
    parse_academic_performance_from_text() for the layout real exports actually use."""
    grade_headers = list(GRADE_HEADER_PATTERN.finditer(section_text))
    semester_labels = list(SEMESTER_LABEL_PATTERN.finditer(section_text))

    items: list[AcademicPerformanceItem] = []
    for row in GRADE_ROW_PATTERN.finditer(section_text):
        grade_anchor = nearest_preceding(grade_headers, row.start())
        semester_anchor = nearest_preceding(semester_labels, row.start())
        if grade_anchor is None or semester_anchor is None:
            continue

        subject = row.group("subject")
        items.append(
            AcademicPerformanceItem(
                grade=int(grade_anchor.group(1)),
                semester=int(semester_anchor.group(1)),
                category=infer_category(subject),
                subject=subject,
                units=int(row.group("units")),
                achievement_grade=row.group("achievement_grade"),
                student_count=int(row.group("student_count")),
                raw_score=float(row.group("raw_score")),
                subject_average=float(row.group("subject_average")),
                std_deviation=float(row.group("std_deviation")),
                rank=row.group("rank"),
            )
        )

    return items
