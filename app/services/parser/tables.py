import re

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


def parse_awards(tables: list[Table]) -> list[AwardItem]:
    items: list[AwardItem] = []
    for table in tables:
        if len(table) < 2:
            continue
        header = [_clean_text(c) for c in table[0]]
        name_idx = _header_index(header, "대회", "수상명")
        rank_idx = _header_index(header, "등급", "수상실적")
        date_idx = _header_index(header, "일자", "날짜", "연월일")
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
            items.append(
                AwardItem(
                    name=name,
                    rank=_cell(cells, rank_idx),
                    date=normalize_date(raw_date),
                    raw_date=raw_date,
                )
            )
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
