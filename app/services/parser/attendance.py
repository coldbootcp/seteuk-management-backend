import re

from app.schemas.seteuk import AttendanceItem
from app.services.parser.anchors import GRADE_HEADER_PATTERN

TOTAL_DAYS_PATTERN = re.compile(r"수업일수\s*[:：]?\s*(\d+)")
ABSENCE_PATTERN = re.compile(r"결석일수\s*[:：]?\s*(\d+)")
NOTE_PATTERN = re.compile(r"특기사항\s*[:：]?\s*(.+)")

Table = list[list[str | None]]
_HEADER_MARKERS = ("학년", "수업일수", "결석일수")


def _to_int(value: str | None) -> int:
    value = (value or "").strip()
    return int(value) if value.isdigit() else 0


def _find_header_row(table: Table) -> int | None:
    for i, row in enumerate(table[:3]):
        cells = [cell or "" for cell in row]
        if all(any(marker in cell for cell in cells) for marker in _HEADER_MARKERS):
            return i
    return None


def parse_attendance_from_tables(tables: list[Table]) -> list[AttendanceItem]:
    """Real 생기부 exports render 출결상황 as a table (학년/수업일수/결석일수(질병·미인정·
    기타)/.../특기사항) rather than the "[N학년] 수업일수: X 결석일수: Y" labeled free text
    docs/PARSER_SPEC.md describes — see parse_attendance() for that fallback."""
    items: list[AttendanceItem] = []
    seen_grades: set[int] = set()

    for table in tables:
        header_row_idx = _find_header_row(table)
        if header_row_idx is None:
            continue

        header = [cell or "" for cell in table[header_row_idx]]
        grade_idx = next(i for i, c in enumerate(header) if "학년" in c)
        total_idx = next(i for i, c in enumerate(header) if "수업일수" in c)
        absence_idx = next(i for i, c in enumerate(header) if "결석일수" in c)
        note_idx = next((i for i, c in enumerate(header) if "특기사항" in c), None)

        for row in table[header_row_idx + 1 :]:
            cells = [cell or "" for cell in row]
            grade_cell = cells[grade_idx].strip() if grade_idx < len(cells) else ""
            if not grade_cell.isdigit():
                continue

            grade = int(grade_cell)
            if grade in seen_grades:
                continue
            seen_grades.add(grade)

            total_days = _to_int(cells[total_idx]) if total_idx < len(cells) else 0
            # 결석일수 spans three sub-columns (질병/미인정/기타) merged under one header.
            absence = sum(
                _to_int(cells[i]) for i in range(absence_idx, absence_idx + 3) if i < len(cells)
            )
            note = (
                cells[note_idx].strip()
                if note_idx is not None and note_idx < len(cells)
                else ""
            )

            items.append(
                AttendanceItem(
                    grade=grade, total_days=total_days, absence=absence, note=note or None
                )
            )

    return items


def parse_attendance(section_text: str) -> list[AttendanceItem]:
    """Fallback for the "[N학년] 수업일수: X 결석일수: Y" labeled-text layout described in
    docs/PARSER_SPEC.md — kept for exports that don't render 출결상황 as a real table."""
    headers = list(GRADE_HEADER_PATTERN.finditer(section_text))
    if not headers:
        return []

    items: list[AttendanceItem] = []
    for i, header in enumerate(headers):
        grade = int(header.group(1))
        start = header.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(section_text)
        block = section_text[start:end]

        total_days_match = TOTAL_DAYS_PATTERN.search(block)
        absence_match = ABSENCE_PATTERN.search(block)
        note_match = NOTE_PATTERN.search(block)

        if total_days_match is None:
            continue

        items.append(
            AttendanceItem(
                grade=grade,
                total_days=int(total_days_match.group(1)),
                absence=int(absence_match.group(1)) if absence_match else 0,
                note=note_match.group(1).strip() if note_match else None,
            )
        )

    return items
