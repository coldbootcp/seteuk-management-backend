import re
from datetime import date

from app.schemas.seteuk import AwardItem, ReadingActivityItem, VolunteerRecordItem
from app.services.parser.dates import normalize_date

Table = list[list[str | None]]

# Real exports don't give 독서활동상황 its own title/author columns — one cell holds a
# free-text "(N학기) 책제목(저자), 책제목(저자), ..." list for the whole semester instead.
BOOK_PATTERN = re.compile(r"([가-힣A-Za-z0-9][^(]*?)\s*\((.*?)\)")
READING_SEMESTER_PATTERN = re.compile(r"\(([1-3])학기\)")


def _clean_text(value: str | None) -> str:
    """Collapse a cell's internal line wrapping (e.g. "교내 환경정리" wrapped mid-word
    as "환\n경정리" to fit the PDF's column width) into single spaces. The wrap point
    is a PDF layout artifact, not a real line break in the source text."""
    return re.sub(r"\s+", " ", value or "").strip()


def _forward_fill(rows: Table) -> list[list[str]]:
    filled: list[list[str]] = []
    last_row: list[str] = []
    for row in rows:
        current: list[str] = []
        for i, cell in enumerate(row):
            value = _clean_text(cell)
            if not value and i < len(last_row):
                value = last_row[i]
            current.append(value)
        filled.append(current)
        last_row = current
    return filled


def _header_index(header: list[str], *aliases: str) -> int | None:
    # Real exports sometimes letter-space header cells for justification (e.g. "학 년"
    # instead of "학년"), so whitespace is stripped from both sides before matching.
    normalized = [col.replace(" ", "") for col in header]
    normalized_aliases = [alias.replace(" ", "") for alias in aliases]
    for i, col in enumerate(normalized):
        if any(alias in col for alias in normalized_aliases):
            return i
    return None


def _cell(row: list[str], index: int | None) -> str | None:
    if index is None or index >= len(row):
        return None
    return row[index] or None


def _find_header_row(table: Table, required: tuple[str, ...]) -> int | None:
    """Some tables put a merged title in row 0 and the real column labels in row 1
    (e.g. 봉사활동실적: row 0 is just "학년 | 봉사활동실적", row 1 has 일자/장소/...).
    Only these first two rows are checked — row 2 onward is already data, and a long
    free-text cell there can coincidentally contain a keyword like "내용" as a word
    inside a sentence, producing a false match."""
    for i, row in enumerate(table[:2]):
        header = [_clean_text(c) for c in row]
        if all(_header_index(header, keyword) is not None for keyword in required):
            return i
    return None


def _academic_year(value: date) -> int:
    """학사연도. 3월에 시작하므로 1~2월은 앞 학년도에 속한다."""
    return value.year if value.month >= 3 else value.year - 1


def _semester_of(value: date) -> int:
    """1학기는 3~8월, 2학기는 9~2월. 수상은 학기 말에 몰려서 이 경계로 충분하다."""
    return 1 if 3 <= value.month <= 8 else 2


_SINGLE_GRADE_RE = re.compile(r"(?<![·‧・,~])\s*([1-3])\s*학년")
_MULTI_GRADE_RE = re.compile(r"[1-3]\s*[·‧・,~]\s*[1-3]\s*학년")


def _grade_from_participants(participants: str) -> int | None:
    """참가대상에서 학년을 읽는다.

    "3학년(216명)"처럼 한 학년만 가리킬 때만 받아들인다. "1·2학년 중 참가자"처럼
    여러 학년이 함께 응모한 대회는 이 학생이 그중 몇 학년이었는지 알 수 없으므로
    여기서 답하지 않고, 같은 문서의 다른 행에서 배운 학년도↔학년 대응에 맡긴다.
    """
    if not participants or _MULTI_GRADE_RE.search(participants):
        return None
    matches = _SINGLE_GRADE_RE.findall(participants)
    return int(matches[0]) if len(set(matches)) == 1 else None


def parse_awards(tables: list[Table]) -> list[AwardItem]:
    items: list[AwardItem] = []
    for table in tables:
        if len(table) < 2:
            continue
        header = [_clean_text(c) for c in table[0]]
        name_idx = _header_index(header, "대회", "수상명")
        rank_idx = _header_index(header, "등급", "수상실적")
        date_idx = _header_index(header, "일자", "날짜", "연월일")
        participants_idx = _header_index(header, "참가대상", "참가")
        if name_idx is None:
            continue

        # No forward-fill here — unlike 학년/과목 grouping columns elsewhere, a blank
        # 등급 cell genuinely means "no rank awarded", not "same rank as the row above".
        for raw_row in table[1:]:
            cells = [_clean_text(c) for c in raw_row]
            name = _cell(cells, name_idx)
            if not name:
                continue
            raw_date = _cell(cells, date_idx)
            participants = _cell(cells, participants_idx)
            items.append(
                AwardItem(
                    name=name,
                    rank=_cell(cells, rank_idx),
                    date=normalize_date(raw_date),
                    raw_date=raw_date,
                    participants=participants,
                    grade=_grade_from_participants(participants or ""),
                )
            )
    return _fill_award_periods(items)


def _fill_award_periods(items: list[AwardItem]) -> list[AwardItem]:
    """수상의 학년-학기를 문서 안에서 완결시킨다.

    학년을 직접 읽어낸 행들이 "이 학사연도가 몇 학년이었는지"를 알려 준다. 그
    대응표로 참가대상이 모호했던 행(교과우수상의 "수강자", 여러 학년 공동 대회 등)의
    학년까지 채운다. 바깥 시계(오늘 날짜)는 쓰지 않는다 — 생기부는 몇 해 전 문서일
    수 있고, 그러면 모든 수상이 학년 범위 밖으로 떨어진다.
    """
    year_to_grade: dict[int, int] = {}
    for item in items:
        if item.grade is None or item.date is None:
            continue
        year_to_grade.setdefault(_academic_year(item.date), item.grade)

    for item in items:
        if item.date is None:
            continue
        if item.grade is None:
            item.grade = year_to_grade.get(_academic_year(item.date))
        if item.grade is not None:
            item.semester = _semester_of(item.date)
    return items


def parse_volunteer_records(tables: list[Table]) -> list[VolunteerRecordItem]:
    items: list[VolunteerRecordItem] = []
    for table in tables:
        if len(table) < 2:
            continue
        # The "학년" label only appears in the table's merged title row, not on the
        # actual column-header row below it — that row is identified by 활동내용
        # instead, and 학년 is always its unlabeled leftmost column.
        header_row_idx = _find_header_row(table, required=("내용",))
        if header_row_idx is None:
            continue

        header = [_clean_text(c) for c in table[header_row_idx]]
        grade_idx = 0
        date_idx = _header_index(header, "일자", "날짜")
        place_idx = _header_index(header, "장소")
        content_idx = _header_index(header, "내용", "활동내용")
        hours_idx = _header_index(header, "시간")

        for row in _forward_fill(table[header_row_idx + 1 :]):
            grade_raw = _cell(row, grade_idx)
            if not grade_raw or not grade_raw.isdigit():
                continue
            raw_date = _cell(row, date_idx)
            hours_raw = _cell(row, hours_idx)
            items.append(
                VolunteerRecordItem(
                    grade=int(grade_raw),
                    date=normalize_date(raw_date),
                    raw_date=raw_date,
                    place=_cell(row, place_idx),
                    content=_cell(row, content_idx),
                    hours=int(hours_raw) if hours_raw and hours_raw.isdigit() else None,
                )
            )
    return items


def _parse_book_list_cell(content: str) -> tuple[int | None, list[tuple[str, str]]]:
    semester_match = READING_SEMESTER_PATTERN.search(content)
    semester = int(semester_match.group(1)) if semester_match else None
    content_clean = READING_SEMESTER_PATTERN.sub("", content).strip()

    books: list[tuple[str, str]] = []
    for raw_title, raw_author in BOOK_PATTERN.findall(content_clean):
        title = raw_title.strip().rstrip(",").strip()
        author = raw_author.replace("(", "").strip()
        if title and author:
            books.append((title, author))
    return semester, books


def parse_reading_activities(tables: list[Table]) -> list[ReadingActivityItem]:
    items: list[ReadingActivityItem] = []
    for table in tables:
        if len(table) < 2:
            continue
        header = [_clean_text(c) for c in table[0]]
        grade_idx = _header_index(header, "학년")
        subject_idx = _header_index(header, "과목", "교과", "영역")
        title_idx = _header_index(header, "도서명", "제목")
        if grade_idx is None:
            continue

        if title_idx is not None:
            # One book per row, title/author already split into their own columns.
            semester_idx = _header_index(header, "학기")
            author_idx = _header_index(header, "저자")
            for row in _forward_fill(table[1:]):
                grade_raw = _cell(row, grade_idx)
                title = _cell(row, title_idx)
                if not grade_raw or not grade_raw.isdigit() or not title:
                    continue
                semester_raw = _cell(row, semester_idx)
                items.append(
                    ReadingActivityItem(
                        grade=int(grade_raw),
                        semester=(
                            int(semester_raw) if semester_raw and semester_raw.isdigit() else None
                        ),
                        subject=_cell(row, subject_idx),
                        title=title,
                        author=_cell(row, author_idx),
                    )
                )
            continue

        # No title column at all — a whole semester's books are packed into one
        # "(N학기) 책제목(저자), 책제목(저자), ..." free-text cell instead.
        content_idx = _header_index(header, "독서활동", "상황", "내용")
        if content_idx is None:
            continue

        for row in _forward_fill(table[1:]):
            grade_raw = _cell(row, grade_idx)
            content = _cell(row, content_idx)
            if not grade_raw or not grade_raw.isdigit() or not content:
                continue

            semester, books = _parse_book_list_cell(content)
            subject = _cell(row, subject_idx)
            for title, author in books:
                items.append(
                    ReadingActivityItem(
                        grade=int(grade_raw),
                        semester=semester,
                        subject=subject,
                        title=title,
                        author=author,
                    )
                )
    return items
