import re

GRADE_HEADER_PATTERN = re.compile(r"\[(\d)학년\]")
SEMESTER_LABEL_PATTERN = re.compile(r"(\d)학기")


def nearest_preceding(anchors: list[re.Match], position: int) -> re.Match | None:
    """Return the anchor match with the greatest start offset that is still <= position."""
    candidate = None
    for anchor in anchors:
        if anchor.start() > position:
            break
        candidate = anchor
    return candidate
