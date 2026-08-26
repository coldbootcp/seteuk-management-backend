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
SCORE_TUPLE_PATTERN = re.compile(
    r"(?P<units>\d+)\s+"
    r"(?P<score>P|\d+/\d+\.\d+(?:\(\d+\.\d+\))?)\s+"
    r"(?P<achievement>[A-EP](?:\(\d+\))?)\s+"
    r"(?P<rank>[1-9]|·)"
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
        is_same_subject_next_semester = (
            next_match is not None and next_match.start() - current.end() < 15
        )

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

    achievement_match = re.match(r"([A-EP])(?:\((\d+)\))?", match["achievement"])
    achievement_grade = achievement_match.group(1) if achievement_match else match["achievement"]
    has_count = achievement_match and achievement_match.group(2)
    student_count = int(achievement_match.group(2)) if has_count else None

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
        rank=None if match["rank"] == "·" else match["rank"],
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
