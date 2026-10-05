import re
from dataclasses import dataclass

from app.models.activity import ActivityCategory

Table = list[list[str | None]]


def _clean_text(cell: str | None) -> str:
    # Collapses a cell's mid-word PDF line wrap into spaces (a layout artifact, not a
    # real line break in the source text).
    return re.sub(r"\s+", " ", cell or "").strip()


_CATEGORY_MAP = {
    "동아리활동": ActivityCategory.CLUB,
    "진로활동": ActivityCategory.CAREER,
}


@dataclass
class ChangcheBlock:
    grade: int
    category: ActivityCategory
    text: str


def parse_changche_blocks(tables: list[Table]) -> list[ChangcheBlock]:
    """창의적체험활동상황 renders as a table whose '영역' column already labels
    자율/동아리/진로 (봉사활동 rows are skipped — see the volunteer_records table
    parsed separately in tables.py). Only the free-text 특기사항 needs the LLM,
    to split it into individual activities; the category itself is not a guess."""
    blocks: list[ChangcheBlock] = []

    for table in tables:
        header_row_idx = None
        for i, row in enumerate(table[:3]):
            joined = "".join(cell or "" for cell in row)
            if "영역" in joined and "특기사항" in joined:
                header_row_idx = i
                break
        if header_row_idx is None:
            continue

        header = [cell or "" for cell in table[header_row_idx]]
        area_idx = next(i for i, c in enumerate(header) if "영역" in c)
        note_idx = next(i for i, c in enumerate(header) if "특기사항" in c)

        current_grade: int | None = None
        current_area = ""
        for row in table[header_row_idx + 1 :]:
            cells = [_clean_text(cell) for cell in row]
            grade_cell = cells[0] if cells else ""
            if grade_cell.isdigit():
                current_grade = int(grade_cell)
            if current_grade is None:
                continue

            area = cells[area_idx] if area_idx < len(cells) else ""
            note = cells[note_idx] if note_idx < len(cells) else ""
            # 새 서식은 영역(동아리·진로 등)을 머리 행에 한 번만 적고, 특기사항은 그 아래
            # 영역 칸이 빈 행에 온다 — 영역을 이어 받지 않으면 전부 자율활동이 된다.
            if area:
                current_area = area
            else:
                area = current_area
            # "희망분야 | 값"은 특기사항 열에 들어 있어도 서술이 아니라 진로희망 항목이다.
            if not note or note.replace(" ", "") == "희망분야":
                continue
            if area == "봉사활동":
                continue

            category = _CATEGORY_MAP.get(area, ActivityCategory.AUTONOMOUS)
            blocks.append(ChangcheBlock(grade=current_grade, category=category, text=note))

    return blocks
