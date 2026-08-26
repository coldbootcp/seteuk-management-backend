import re
from dataclasses import dataclass

from app.services.parser.anchors import (
    GRADE_HEADER_PATTERN,
    SEMESTER_LABEL_PATTERN,
    nearest_preceding,
)


@dataclass
class TextBlock:
    grade: int
    semester: int | None
    subject: str | None
    text: str


def slice_subject_blocks(section_text: str, subjects: list[str]) -> list[TextBlock]:
    """Split 세특 text on subject-name anchors from the whitelist extracted by grades.py.

    A single regex covering every notation variant (국어:, 국어 :, 한국사(1학기): ...) is
    deliberately avoided — see docs/PARSER_SPEC.md 2.1. Instead each whitelisted subject
    name anchors an optional trailing "(...)" plus a colon.
    """
    if not subjects:
        return []

    ordered_subjects = sorted(set(subjects), key=len, reverse=True)
    anchor_pattern = re.compile(
        "(" + "|".join(re.escape(s) for s in ordered_subjects) + r")\s*(?:\([^)]*\))?\s*:"
    )
    anchors = list(anchor_pattern.finditer(section_text))
    grade_headers = list(GRADE_HEADER_PATTERN.finditer(section_text))
    semester_labels = list(SEMESTER_LABEL_PATTERN.finditer(section_text))

    blocks: list[TextBlock] = []
    for i, anchor in enumerate(anchors):
        grade_anchor = nearest_preceding(grade_headers, anchor.start())
        if grade_anchor is None:
            continue

        start = anchor.end()
        end = anchors[i + 1].start() if i + 1 < len(anchors) else len(section_text)
        # PDF line wrapping is a layout artifact here, not a real paragraph break.
        text = re.sub(r"\s+", " ", section_text[start:end]).strip()
        if not text:
            continue

        semester_anchor = nearest_preceding(semester_labels, anchor.start())
        blocks.append(
            TextBlock(
                grade=int(grade_anchor.group(1)),
                semester=int(semester_anchor.group(1)) if semester_anchor else None,
                subject=anchor.group(1),
                text=text,
            )
        )

    return blocks


def slice_grade_semester_blocks(section_text: str) -> list[TextBlock]:
    """Split 창체/행발 text on [N학년] / N학기 headers only — no subject whitelist involved."""
    grade_headers = list(GRADE_HEADER_PATTERN.finditer(section_text))

    blocks: list[TextBlock] = []
    for i, header in enumerate(grade_headers):
        grade = int(header.group(1))
        start = header.end()
        end = grade_headers[i + 1].start() if i + 1 < len(grade_headers) else len(section_text)
        block_text = section_text[start:end]

        semester_labels = list(SEMESTER_LABEL_PATTERN.finditer(block_text))
        if not semester_labels:
            stripped = block_text.strip()
            if stripped:
                blocks.append(TextBlock(grade=grade, semester=None, subject=None, text=stripped))
            continue

        for j, sem in enumerate(semester_labels):
            s_start = sem.end()
            s_end = (
                semester_labels[j + 1].start() if j + 1 < len(semester_labels) else len(block_text)
            )
            text = block_text[s_start:s_end].strip()
            if text:
                blocks.append(
                    TextBlock(grade=grade, semester=int(sem.group(1)), subject=None, text=text)
                )

    return blocks
