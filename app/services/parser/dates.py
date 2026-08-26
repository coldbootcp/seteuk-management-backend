import re
from datetime import date

_DATE_PATTERNS = [
    re.compile(r"(?P<y>\d{4})[.\-/](?P<m>\d{1,2})[.\-/](?P<d>\d{1,2})"),
    re.compile(r"(?P<y>\d{4})년\s*(?P<m>\d{1,2})월\s*(?P<d>\d{1,2})일"),
]


def normalize_date(raw_date: str | None) -> date | None:
    if not raw_date:
        return None

    for pattern in _DATE_PATTERNS:
        match = pattern.search(raw_date)
        if match:
            try:
                return date(int(match["y"]), int(match["m"]), int(match["d"]))
            except ValueError:
                return None

    return None
