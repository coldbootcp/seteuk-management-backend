import re
from dataclasses import dataclass

Table = list[list[str | None]]


def _clean_text(cell: str | None) -> str:
    # Collapses a cell's mid-word PDF line wrap into spaces (a layout artifact, not a
    # real line break in the source text).
    return re.sub(r"\s+", " ", cell or "").strip()


@dataclass
class BehaviorBlock:
    grade: int
    text: str


def parse_behavior_blocks(tables: list[Table]) -> list[BehaviorBlock]:
    """행동특성 및 종합의견 renders as a 학년/내용 table. A grade's narrative can span
    a page break, becoming two separate table objects with the grade number repeated
    as the row label on each — so text is concatenated by grade across all tables."""
    grouped: dict[int, list[str]] = {}

    for table in tables:
        header_row_idx = None
        for i, row in enumerate(table[:2]):
            joined = "".join((cell or "").replace(" ", "") for cell in row)
            if "학년" in joined and "행동특성" in joined:
                header_row_idx = i
                break
        if header_row_idx is None:
            continue

        for row in table[header_row_idx + 1 :]:
            cells = [_clean_text(cell) for cell in row]
            if not cells:
                continue
            grade_cell = cells[0]
            text = cells[1] if len(cells) > 1 else ""
            if not grade_cell.isdigit() or not text:
                continue
            grouped.setdefault(int(grade_cell), []).append(text)

    return [BehaviorBlock(grade=grade, text=" ".join(parts)) for grade, parts in grouped.items()]
