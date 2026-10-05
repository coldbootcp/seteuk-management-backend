import re

from app.schemas.seteuk import VolunteerRecordItem
from app.services.academic_year import semester_of
from app.services.parser.dates import normalize_date

Table = list[list[str | None]]


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


def parse_volunteer_records(tables: list[Table]) -> list[VolunteerRecordItem]:
    items: list[VolunteerRecordItem] = []
    for table in tables:
        if len(table) < 2:
            continue
        # 봉사는 "봉 사 활 동 실 적" 표에서만 읽는다. "내용"이라는 낱말만으로 표를
        # 고르면 세특처럼 본문에 그 말이 우연히 들어간 표까지 걸린다(실제로 걸렸다).
        # 제목 행에 봉사가 적혀 있고, 머리글에 일자와 시간이 함께 있어야 그 표다.
        # 자간 공백("봉 사 활 동")은 이 문서의 제목 행 관례라 지우고 본다.
        if "봉사활동" not in "".join(_clean_text(c) for c in table[0]).replace(" ", ""):
            continue
        header_row_idx = _find_header_row(table, required=("내용", "일자", "시간"))
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
            # 학년은 표가 직접 알려 주고, 학기는 날짜의 달에서 나온다
            # (3~8월 1학기, 9~2월 2학기).
            date = normalize_date(raw_date)
            items.append(
                VolunteerRecordItem(
                    grade=int(grade_raw),
                    semester=semester_of(date) if date else None,
                    date=date,
                    raw_date=raw_date,
                    place=_cell(row, place_idx),
                    content=_cell(row, content_idx),
                    hours=int(hours_raw) if hours_raw and hours_raw.isdigit() else None,
                )
            )
    return items


_DATE_TOKEN = re.compile(r"\d{4}\.\d{1,2}\.\d{1,2}\.?")
# 표 폭에서 각 열 경계의 위치(비율). 새 서식의 봉사활동 표는 안쪽 세로선이 없고 열이
# 왼쪽 맞춤이라, 표 왼쪽·오른쪽 끝(제목 행의 가로선)에서 잰 비율로 열을 가른다.
_COL_PLACE, _COL_CONTENT, _COL_HOURS, _COL_TOTAL = 0.284, 0.51, 0.856, 0.917


def parse_volunteer_from_layout(pdf_bytes: bytes) -> list[VolunteerRecordItem]:
    """봉사활동 표의 행이 한 칸에 뭉쳐 오는 서식을 단어 좌표로 다시 세운다.

    새 서식은 학년마다 모든 봉사 기록이 셀 하나에 줄바꿈으로 들어와, 표로 읽으면 학년당
    한 건(시간·내용 없음)이 된다. 날짜가 있는 줄을 행의 기준으로 삼고, 나머지 단어는 세로로
    가장 가까운 기준 줄에 붙인다(내용이 두 줄로 접히면 날짜 줄 위아래에 놓인다). 학년은 표가
    한 번만 적어 주므로 누계시간이 되돌아가는 지점에서 갈라 가장 가까운 학년 숫자에 잇는다.
    """
    import io

    import pdfplumber

    items: list[VolunteerRecordItem] = []
    grade: int | None = None
    prev_total = 0
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            if "봉사활동실적" not in "".join(w["text"] for w in words):
                continue
            frame = [w for w in words if w["text"] == "일자"]
            head_y = frame[0]["top"] if frame else None
            # 열 기준은 머리글 위쪽의 제목·머리글 가로선으로만 잰다. 본문 쪽에 덧그려진 선(도장,
            # 가림 상자 등)이 표 폭을 흐트러뜨리지 않게 한다.
            rules = [
                e
                for e in page.horizontal_edges
                if e["x1"] - e["x0"] > 300 and e["top"] < (head_y or 0)
            ]
            if head_y is None or not rules:
                continue
            left = min(e["x0"] for e in rules)
            width = max(e["x1"] for e in rules) - left

            def col(x: float, left: float = left, width: float = width) -> int:
                ratio = (x - left) / width
                return sum(ratio >= b for b in (_COL_PLACE, _COL_CONTENT, _COL_HOURS, _COL_TOTAL))

            body = [w for w in words if w["top"] > head_y + 8 and w["top"] < page.height - 80]
            digits = [w for w in body if w["x1"] < left and w["text"].isdigit()]
            anchors = sorted(
                (w for w in body if col(w["x0"]) == 0 and _DATE_TOKEN.fullmatch(w["text"])),
                key=lambda w: (w["top"], w["x0"]),
            )
            if anchors:
                # 표 아래의 쪽번호·반·번호·이름 칸이 마지막 행에 붙지 않게 자른다.
                limit = anchors[-1]["top"] + 15
                body = [w for w in body if w["top"] <= limit]
                digits = [w for w in digits if w["top"] <= limit]
            rows: list[dict] = []
            for w in anchors:
                if rows and abs(rows[-1]["top"] - w["top"]) < 3:
                    rows[-1]["date"].append(w["text"])
                else:
                    rows.append({"top": w["top"], "date": [w["text"]], "cells": {}})
            if not rows:
                continue
            for w in body:
                if w in digits or w in anchors:
                    continue
                c = col(w["x0"])
                # 날짜 줄의 "-"·"~"(기간 표기)는 날짜 칸에 이어 붙인다.
                nearest = min(rows, key=lambda r: abs(r["top"] - w["top"]))
                if c == 0 and w["text"] in ("-", "~") and abs(nearest["top"] - w["top"]) < 3:
                    nearest["date"].append(w["text"])
                elif c == 0:
                    continue
                else:
                    nearest["cells"].setdefault(c, []).append(w)

            groups: list[list[dict]] = []
            for row in rows:
                nums = [x["text"] for x in sorted(row["cells"].get(4, []), key=lambda x: x["x0"])]
                row["total"] = int(nums[-1]) if nums and nums[-1].isdigit() else None
                total = row["total"] or 0
                if not groups or total <= prev_total:
                    groups.append([])
                groups[-1].append(row)
                prev_total = total

            for group in groups:
                center = sum(r["top"] for r in group) / len(group)
                if digits:
                    pick = min(digits, key=lambda d: abs(d["top"] - center))
                    grade = int(pick["text"])
                elif grade is None:
                    continue
                for row in group:
                    text = lambda c, row=row: " ".join(  # noqa: E731
                        x["text"]
                        for x in sorted(
                            row["cells"].get(c, []), key=lambda x: (round(x["top"]), x["x0"])
                        )
                    )
                    date_tokens = [t for t in row["date"] if _DATE_TOKEN.fullmatch(t)]
                    date = normalize_date(date_tokens[0]) if date_tokens else None
                    hours_text = text(3)
                    items.append(
                        VolunteerRecordItem(
                            grade=grade,
                            semester=semester_of(date) if date else None,
                            date=date,
                            raw_date=" ".join(row["date"]),
                            place=text(1) or None,
                            content=text(2) or None,
                            hours=int(hours_text) if hours_text.isdigit() else None,
                        )
                    )
    return items
