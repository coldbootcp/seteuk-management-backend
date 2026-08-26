import re

from app.models.activity import ActivityCategory, ActivityType
from app.schemas.seteuk import ActivityItem

Table = list[list[str | None]]


def _normalize(cell: str | None) -> str:
    return (cell or "").replace(" ", "").replace("\n", "")


def _clean_text(cell: str | None) -> str:
    # Collapses a cell's mid-word PDF line wrap (e.g. "기계공\n학 연구원") into spaces.
    return re.sub(r"\s+", " ", cell or "").strip()


def parse_career_aspirations(tables: list[Table]) -> list[ActivityItem]:
    """진로희망사항 renders as a plain 학년/진로희망/희망사유 table — no LLM needed."""
    items: list[ActivityItem] = []

    for table in tables:
        if not table:
            continue
        header = [_normalize(cell) for cell in table[0]]
        grade_idx = next((i for i, c in enumerate(header) if c == "학년"), None)
        hope_idx = next((i for i, c in enumerate(header) if "진로희망" in c), None)
        reason_idx = next((i for i, c in enumerate(header) if "사유" in c), None)
        if grade_idx is None or hope_idx is None:
            continue

        for row in table[1:]:
            cells = [_clean_text(cell) for cell in row]
            grade_cell = cells[grade_idx] if grade_idx < len(cells) else ""
            hope = cells[hope_idx] if hope_idx < len(cells) else ""
            if not grade_cell.isdigit() or not hope:
                continue

            reason = cells[reason_idx] if reason_idx is not None and reason_idx < len(cells) else ""

            items.append(
                ActivityItem(
                    grade=int(grade_cell),
                    semester=None,
                    activity_category=ActivityCategory.CAREER,
                    subject=None,
                    activity_name=hope,
                    activity_type=ActivityType.OTHER,
                    role=None,
                    description=reason or hope,
                    keywords=[],
                    source_block=" / ".join(c for c in cells if c),
                )
            )

    return items
