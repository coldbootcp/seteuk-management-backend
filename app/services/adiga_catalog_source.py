"""대입정보포털(어디가) 일반대학 모집 정보의 작은 읽기 전용 어댑터.

대입정보포털의 일반대학 화면은 4년제 대학과 전문대학을 서로 다른 경로로
분리한다. 이 모듈은 일반대학 경로만 사용하며, 원문 URL과 확인 시각은 카탈로그
행에 함께 남긴다. 포털 내부 코드는 외부 API 계약이 아니므로, 호출 실패 시
기존에 저장한 카탈로그를 지우지 않는 것이 원칙이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser

import httpx

BASE_URL = "https://www.adiga.kr"
UNIVERSITY_VIEW_URL = f"{BASE_URL}/ucp/uvt/uni/univView.do?menuId=PCUVTINF2000"
ADMISSION_VIEW_URL = f"{BASE_URL}/ucp/prc/uni/admssUnivView.do?menuId=PCPRCINF2000"
ADMISSION_LIST_URL = f"{BASE_URL}/ucp/prc/uni/admssUnivAjax.do"
ADMISSION_TRACKS_URL = f"{BASE_URL}/ucp/prc/uni/admssUnivDetailLstAjax.do"
UNIVERSITY_STATISTICS_URL = f"{BASE_URL}/ucp/uvt/uni/univMainChartAjax.do"
UNIVERSITY_ADMISSION_GUIDE_URL = (
    f"{BASE_URL}/ucp/uvt/uni/univDetailAdmission.do?menuId=PCUVTINF2000"
)
UNIVERSITY_SUBJECT_VIEW_URL = f"{BASE_URL}/ucp/uvt/uni/univDetailSubject.do?menuId=PCUVTINF2000"
UNIVERSITY_SUBJECT_LIST_URL = f"{BASE_URL}/ucp/uvt/uni/univDetailSubjectAjax.do"
PROGRAM_OUTCOMES_URL = f"{BASE_URL}/ucp/cls/uni/classUnivAdmssPopup.do"

_CSRF_PATTERN = re.compile(r'<meta name="_csrf" content="([^"]+)">')
_TAG_PATTERN = re.compile(r"<[^>]+>")
_UNIVERSITY_PATTERN = re.compile(
    r'<input[^>]+name="searchUnvCode"[^>]+value="(?P<code>[^"]+)"[^>]*/>\s*'
    r'<label[^>]*>\s*(?P<label>.*?)\s*<strong>',
    re.DOTALL,
)
_PROGRAM_BLOCK_PATTERN = re.compile(
    r'<div class="norList vw">(?P<block>.*?)</div>\s*<!-- // 목록 영역-->', re.DOTALL
)
_PROGRAM_PATTERN = re.compile(
    r'<li class="col01[^>]*unvCd="(?P<university_code>[^"]+)"\s+'
    r'comScsbjtCd="(?P<program_code>[^"]+)"[^>]*>.*?'
    r'<span class="body1 reg left">(?P<university_name>.*?)</span>.*?'
    r'<li class="col02[^>]*>.*?<span class="body1 reg"[^>]*>'
    r'(?P<program_name>.*?)</span>.*?'
    r'<li class="col03[^>]*>.*?<span class="body1 reg">(?P<region>.*?)</span>',
    re.DOTALL,
)
_TRACK_PATTERN = re.compile(
    r'<a[^>]+onclick="fnDetailPage\(&quot;(?P<university_code>[^&]+)&quot;,'
    r'&quot;(?P<program_code>[^&]+)&quot;,&quot;(?P<track_code>[^&]+)&quot;,'
    r'&quot;(?P<period_code>[^&]+)&quot;.*?\);">(?P<name>.*?)</a>',
    re.DOTALL,
)
_SECTION_START_PATTERN = re.compile(r'id="con_(?P<section>\d+)"[^>]*>')
# 학과가 하나라도 정시/수시 경쟁률을 공개하지 않으면, 이전의 단일 정규식은 다음
# ``boxMajor`` 블록까지 되돌아가며 탐색했다. 특히 대구한의대처럼 블록이 많은 페이지에서
# 지수적으로 느려질 수 있어, 각 학과 블록 안에서 독립적으로 필요한 값을 찾는다.
_PROGRAM_REFERENCE_CODE_PATTERN = re.compile(
    r'fnDetailPage\(&quot;(?P<reference_code>[^&]+)&quot;\)'
)
_PROGRAM_REFERENCE_NAME_PATTERN = re.compile(r'<span class="tit">(?P<name>.*?)</span>', re.DOTALL)
_PROGRAM_REFERENCE_FIELD_PATTERN = re.compile(r'<span>(?P<academic_field>.*?)</span>', re.DOTALL)
_PROGRAM_REFERENCE_RECRUITMENT_PATTERN = re.compile(
    r'<span class="desc">모집인원</span>\s*<span class="no">(?P<recruitment_count>.*?)</span>',
    re.DOTALL,
)
_PROGRAM_REFERENCE_EARLY_RATIO_PATTERN = re.compile(
    r'<span class="type">수시</span>\s*(?P<ratio>[\d.]+)\s*:\s*1'
)
_PROGRAM_REFERENCE_REGULAR_RATIO_PATTERN = re.compile(
    r'<span class="type">정시</span>\s*(?P<ratio>[\d.]+)\s*:\s*1'
)
_PROGRAM_PROFILE_SECTION_PATTERN = re.compile(
    r'<div class="classCon">\s*<h4[^>]*>(?P<title>.*?)</h4>\s*'
    r'<p[^>]*>(?P<content>.*?)</p>',
    re.DOTALL,
)
_ADMISSION_GUIDE_BODY_PATTERN = re.compile(
    r'<p(?:\s+class="required")?[^>]*>\s*(?P<label>\d{4}학년도\s*'
    r'(?:대입특징|입시가이드)\s*자료입니다\.)\s*</p>.*?'
    r'<div>\s*<html\b.*?<body>(?P<body>.*?)</body>\s*</html>\s*</div>',
    re.DOTALL,
)


class AdigaSourceError(RuntimeError):
    """공식 원천의 응답 형식 또는 네트워크가 기대와 다를 때 사용한다."""


@dataclass(frozen=True)
class AdigaUniversity:
    official_code: str
    name: str
    campus_name: str | None


@dataclass(frozen=True)
class AdigaProgram:
    university_code: str
    program_code: str
    university_name: str
    name: str
    region: str | None


@dataclass(frozen=True)
class AdigaTrack:
    track_code: str
    name: str
    admission_type: str | None
    recruitment_period: str | None


@dataclass(frozen=True)
class AdigaUniversityStatistics:
    """공개 차트 응답에서 학생에게 의미 있는 수치만 정리한 대학 단위 통계."""

    source_url: str
    payload: dict[str, list[dict[str, int | float | str | None]]]


@dataclass(frozen=True)
class AdigaProgramReference:
    source_reference_code: str
    name: str
    academic_field: str | None
    recruitment_count: int | None
    early_competition_rate: float | None
    regular_competition_rate: float | None


@dataclass(frozen=True)
class AdigaProgramOutcome:
    recruitment_period: str | None
    selection_type: str | None
    selection_name: str | None
    initial_recruitment_count: int | None
    transferred_recruitment_count: int | None
    final_recruitment_count: int | None
    competition_rate: float | None
    additional_admission_count: int | None
    metrics: dict[str, str]


@dataclass(frozen=True)
class AdigaUniversityAdmissionGuide:
    """대학의 수시·정시 대입특징 및 입시가이드를 보존한 원천 결과."""

    source_url: str
    sections: list[dict[str, object]]


@dataclass
class _HtmlCell:
    text: list[str]
    colspan: int
    rowspan: int


@dataclass
class _HtmlTable:
    header_rows: list[list[_HtmlCell]]
    body_rows: list[list[_HtmlCell]]


class _TableParser(HTMLParser):
    """외부 의존성 없이 어디가의 표를 행·셀 단위로 읽는 최소 파서."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[_HtmlTable] = []
        self._table_stack: list[_HtmlTable] = []
        self._current_rows: list[list[_HtmlCell]] = []
        self._section_stack: list[str] = []
        self._cells: list[_HtmlCell] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "table":
            table = _HtmlTable(header_rows=[], body_rows=[])
            self.tables.append(table)
            self._table_stack.append(table)
        elif tag in {"thead", "tbody"}:
            self._section_stack.append(tag)
        elif tag == "tr" and self._table_stack:
            self._current_rows.append([])
        elif tag in {"th", "td"} and self._table_stack and self._current_rows:
            def span(name: str) -> int:
                try:
                    return max(int(attributes.get(name) or "1"), 1)
                except ValueError:
                    return 1

            cell = _HtmlCell(text=[], colspan=span("colspan"), rowspan=span("rowspan"))
            self._current_rows[-1].append(cell)
            self._cells.append(cell)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"th", "td"} and self._cells:
            self._cells.pop()
        elif tag == "tr" and self._table_stack and self._current_rows:
            row = self._current_rows.pop()
            section = self._section_stack[-1] if self._section_stack else "tbody"
            current_table = self._table_stack[-1]
            target = current_table.header_rows if section == "thead" else current_table.body_rows
            target.append(row)
        elif tag in {"thead", "tbody"} and self._section_stack:
            self._section_stack.pop()
        elif tag == "table" and self._table_stack:
            self._table_stack.pop()

    def handle_data(self, data: str) -> None:
        if self._cells:
            self._cells[-1].text.append(data)


class _GuideParagraphParser(HTMLParser):
    """표 밖의 문단·목록만 읽는다. 표는 별도의 표 파서가 그대로 보존한다."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[str] = []
        self._table_depth = 0
        self._current: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag == "table":
            self._table_depth += 1
        elif tag in {"p", "li"} and self._table_depth == 0:
            self._current = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            self._table_depth = max(self._table_depth - 1, 0)
        elif tag in {"p", "li"} and self._current is not None:
            text = " ".join("".join(self._current).split())
            if text:
                self.paragraphs.append(text)
            self._current = None

    def handle_data(self, data: str) -> None:
        if self._current is not None and self._table_depth == 0:
            self._current.append(data)


def _table_grid(rows: list[list[_HtmlCell]]) -> list[list[str]]:
    """rowspan/colspan을 펼쳐 각 열 위치를 맞춘 표 그리드."""
    grid_rows: list[list[str]] = []
    carried: dict[int, tuple[int, str]] = {}
    for row in rows:
        grid: dict[int, str] = {}
        next_carried: dict[int, tuple[int, str]] = {}
        for column, (remaining, value) in carried.items():
            grid[column] = value
            if remaining > 1:
                next_carried[column] = (remaining - 1, value)
        column = 0
        for cell in row:
            while column in grid:
                column += 1
            value = " ".join("".join(cell.text).split())
            for offset in range(cell.colspan):
                target_column = column + offset
                grid[target_column] = value
                if cell.rowspan > 1:
                    next_carried[target_column] = (cell.rowspan - 1, value)
            column += cell.colspan
        carried = next_carried
        width = max(grid, default=-1) + 1
        grid_rows.append([grid.get(index, "") for index in range(width)])
    width = max((len(row) for row in grid_rows), default=0)
    return [row + [""] * (width - len(row)) for row in grid_rows]


def _as_int(value: str) -> int | None:
    cleaned = value.replace(",", "").strip()
    try:
        return int(cleaned) if cleaned not in {"", "-"} else None
    except ValueError:
        return None


def _as_float(value: str) -> float | None:
    cleaned = value.replace(":1", "").replace(",", "").strip()
    try:
        return float(cleaned) if cleaned not in {"", "-"} else None
    except ValueError:
        return None


def _header_labels(header_rows: list[list[str]]) -> list[str]:
    if not header_rows:
        return []
    labels: list[str] = []
    for column in range(max(len(row) for row in header_rows)):
        parts: list[str] = []
        for row in header_rows:
            value = row[column] if column < len(row) else ""
            if value and value not in parts:
                parts.append(value)
        labels.append(" / ".join(parts))
    return labels


def _plain_text(value: str) -> str:
    return " ".join(unescape(_TAG_PATTERN.sub("", value)).split())


def _split_campus(label: str) -> tuple[str, str | None]:
    match = re.fullmatch(r"(?P<name>.+?)\[(?P<campus>[^\]]+)\]", label)
    return (match.group("name"), match.group("campus")) if match else (label, None)


def parse_general_universities(html: str) -> list[AdigaUniversity]:
    rows: dict[str, AdigaUniversity] = {}
    for match in _UNIVERSITY_PATTERN.finditer(html):
        label = _plain_text(match.group("label"))
        if not label:
            continue
        name, campus_name = _split_campus(label)
        rows[match.group("code")] = AdigaUniversity(match.group("code"), name, campus_name)
    return list(rows.values())


def parse_programs(html: str) -> list[AdigaProgram]:
    rows: dict[tuple[str, str], AdigaProgram] = {}
    for block in _PROGRAM_BLOCK_PATTERN.finditer(html):
        match = _PROGRAM_PATTERN.search(block.group("block"))
        if not match:
            continue
        university_code = match.group("university_code")
        program_code = match.group("program_code")
        rows[(university_code, program_code)] = AdigaProgram(
            university_code=university_code,
            program_code=program_code,
            university_name=_plain_text(match.group("university_name")),
            name=_plain_text(match.group("program_name")),
            region=_plain_text(match.group("region")) or None,
        )
    return list(rows.values())


def parse_tracks(html: str, *, university_code: str, program_code: str) -> list[AdigaTrack]:
    rows: dict[tuple[str, str], AdigaTrack] = {}
    for match in _TRACK_PATTERN.finditer(html):
        if (
            match.group("university_code") != university_code
            or match.group("program_code") != program_code
        ):
            continue
        name = _plain_text(match.group("name"))
        if not name:
            continue
        type_label, _, _ = name.partition(" > ")
        period_code = match.group("period_code")
        period = {"20": "수시", "31": "정시(가)", "32": "정시(나)", "33": "정시(다)"}.get(
            period_code, period_code
        )
        rows[(match.group("track_code"), name)] = AdigaTrack(
            track_code=match.group("track_code"),
            name=name,
            admission_type=type_label or None,
            recruitment_period=period,
        )
    return list(rows.values())


def parse_program_references(html: str) -> list[AdigaProgramReference]:
    """설치학과 목록의 공개 모집/경쟁률 요약과 어디가 학과코드를 읽는다."""
    rows: dict[str, AdigaProgramReference] = {}
    # 반드시 각각의 학과 카드로 범위를 제한한다. 원천의 어떤 카드가 일부 지표를
    # 빠뜨려도 이후 카드까지 탐색하지 않아 대량 수집이 멈추지 않는다.
    for block in html.split('<li class="boxMajor">')[1:]:
        code_match = _PROGRAM_REFERENCE_CODE_PATTERN.search(block)
        name_match = _PROGRAM_REFERENCE_NAME_PATTERN.search(block)
        if code_match is None or name_match is None:
            continue
        reference_code = code_match.group("reference_code")
        name = _plain_text(name_match.group("name"))
        if not reference_code or not name:
            continue
        field_match = _PROGRAM_REFERENCE_FIELD_PATTERN.search(block)
        recruitment_match = _PROGRAM_REFERENCE_RECRUITMENT_PATTERN.search(block)
        early_ratio_match = _PROGRAM_REFERENCE_EARLY_RATIO_PATTERN.search(block)
        regular_ratio_match = _PROGRAM_REFERENCE_REGULAR_RATIO_PATTERN.search(block)
        try:
            recruitment_count = int(
                _plain_text(recruitment_match.group("recruitment_count")).replace(",", "")
            ) if recruitment_match else None
        except ValueError:
            recruitment_count = None
        rows[reference_code] = AdigaProgramReference(
            source_reference_code=reference_code,
            name=name,
            academic_field=(
                _plain_text(field_match.group("academic_field")) if field_match else None
            ) or None,
            recruitment_count=recruitment_count,
            early_competition_rate=(
                float(early_ratio_match.group("ratio")) if early_ratio_match else None
            ),
            regular_competition_rate=(
                float(regular_ratio_match.group("ratio")) if regular_ratio_match else None
            ),
        )
    return list(rows.values())


def parse_program_outcomes(html: str) -> list[AdigaProgramOutcome]:
    """학과 상세의 공개 입시결과 표를 공통 열과 원본 지표로 나눠 읽는다."""
    parser = _TableParser()
    parser.feed(html)
    parser.close()

    for table in parser.tables:
        header_rows = _table_grid(table.header_rows)
        header_labels = _header_labels(header_rows)
        if not {"모집시기", "전형유형", "전형명", "경쟁률"}.issubset(
            {label.replace(" ", "") for label in header_labels}
        ):
            continue
        outcomes: list[AdigaProgramOutcome] = []
        for row in _table_grid(table.body_rows):
            if len(row) < 8 or not any(row[:3]):
                continue
            metrics = {
                header_labels[index]: value
                for index, value in enumerate(row[8:], 8)
                if index < len(header_labels) and header_labels[index] and value not in {"", "-"}
            }
            outcomes.append(
                AdigaProgramOutcome(
                    recruitment_period=row[0] or None,
                    selection_type=row[1] or None,
                    selection_name=row[2] or None,
                    initial_recruitment_count=_as_int(row[3]),
                    transferred_recruitment_count=_as_int(row[4]),
                    final_recruitment_count=_as_int(row[5]),
                    competition_rate=_as_float(row[6]),
                    additional_admission_count=_as_int(row[7]),
                    metrics=metrics,
                )
            )
        return outcomes
    return []


def parse_program_profile_sections(html: str) -> list[dict[str, list[str] | str]]:
    """학과 소개의 교육목표·교육과정·진로취업분야만 구조화한다."""
    target_titles = {"교육목표", "교육과정", "진로취업분야"}
    sections: list[dict[str, list[str] | str]] = []
    for match in _PROGRAM_PROFILE_SECTION_PATTERN.finditer(html):
        title = _plain_text(match.group("title"))
        if title not in target_titles:
            continue
        content = _plain_text(match.group("content"))
        if not content:
            continue
        items = [item.strip() for item in content.split(",") if item.strip()]
        # 교육목표는 문장 전체가 의미 단위라 쉼표로 자르지 않는다.
        sections.append({"title": title, "items": [content] if title == "교육목표" else items})
    return sections


def _guide_section(title: str, body: str) -> dict[str, object]:
    """대입 가이드의 한 HTML 본문을 문단과 표의 손실 없는 읽기 구조로 바꾼다."""
    paragraphs_parser = _GuideParagraphParser()
    paragraphs_parser.feed(body)
    paragraphs_parser.close()

    tables_parser = _TableParser()
    tables_parser.feed(body)
    tables_parser.close()
    tables: list[dict[str, list[list[str]]]] = []
    for table in tables_parser.tables:
        rows = _table_grid([*table.header_rows, *table.body_rows])
        rows = [row for row in rows if any(cell.strip() for cell in row)]
        if rows:
            tables.append({"rows": rows})

    return {
        "title": title,
        "paragraphs": list(dict.fromkeys(paragraphs_parser.paragraphs)),
        "tables": tables,
    }


def parse_university_admission_guide(html: str) -> list[dict[str, object]]:
    """어디가 대학 페이지의 수시·정시 특징과 입시가이드 세 탭을 읽는다.

    포털이 탭을 같은 문구(예: '대입특징 자료입니다')로 표시하므로, 공식 화면의
    고정 순서인 수시 → 정시 → 입시가이드로 제목을 명시한다. 내용이 누락된 탭은
    생성하지 않아 빈 정보를 실제 안내처럼 보이지 않게 한다.
    """
    titles = ("수시 대입특징", "정시 대입특징", "입시가이드")
    sections: list[dict[str, object]] = []
    for index, match in enumerate(_ADMISSION_GUIDE_BODY_PATTERN.finditer(html)):
        body = match.group("body")
        parsed = _guide_section(
            titles[index] if index < len(titles) else _plain_text(match.group("label")), body
        )
        if parsed["paragraphs"] or parsed["tables"]:
            sections.append(parsed)
    return sections


def parse_track_reference(
    html: str, track_name: str
) -> tuple[bool | None, bool | None, bool | None, str] | None:
    """공식 자료의 전형군 구간을 읽되, 전형별로 확인되지 않은 값은 비워 둔다.

    어디가 공개 페이지의 ``con_21`` 같은 본문은 내부 HTML이 중첩돼 있어 닫는 태그를
    기준으로 자르면 쉽게 끊긴다. 다음 전형군 시작점까지 잘라 읽는 방식으로 바꾼다.
    특히 면접·수능최저는 같은 전형군 안에서도 모집단위마다 다를 수 있으므로, 전형명과
    정확히 대응하는 근거를 찾지 못하면 추측해 채우지 않는다.
    """
    group = track_name.split(" > ", maxsplit=1)[0].replace(" ", "")
    group_config = {
        "학생부위주(종합)": ("2", "학생부종합전형", True),
        "학생부위주(교과)": ("3", "학생부교과전형", True),
        "수능위주": ("4", "수능위주전형", None),
    }.get(group)
    if not group_config:
        return None

    section_prefix, group_label, document = group_config
    starts = list(_SECTION_START_PATTERN.finditer(html))
    for match in starts:
        if not match.group("section").startswith(section_prefix):
            continue
        return (
            document,
            None,
            None,
            f"{group_label} 전형군의 {group_label} 관련 공식 공개 자료입니다. "
            "면접과 수능최저는 모집단위·세부 전형별 적용 여부가 달라 "
            "원문에서 다시 확인해야 합니다.",
        )
    return None


def _csrf_token(html: str) -> str:
    match = _CSRF_PATTERN.search(html)
    if not match:
        raise AdigaSourceError("대입정보포털의 요청 검증 값을 읽지 못했습니다.")
    return match.group(1)


class AdigaCatalogSource:
    """공식 화면과 같은 POST 요청만 사용한다. 응답을 재배포하지 않는다."""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(45.0, connect=15.0),
            follow_redirects=True,
            headers={"User-Agent": "SeteukLab catalog verifier/1.0"},
        )
        self.verified_at: datetime | None = None

    async def __aenter__(self) -> AdigaCatalogSource:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._client.aclose()

    async def _open_admission_session(self) -> str:
        response = await self._client.get(ADMISSION_VIEW_URL)
        response.raise_for_status()
        return _csrf_token(response.text)

    async def fetch_general_universities(self) -> list[AdigaUniversity]:
        response = await self._client.get(UNIVERSITY_VIEW_URL)
        response.raise_for_status()
        rows = parse_general_universities(response.text)
        if not rows:
            raise AdigaSourceError("일반대학 목록을 읽지 못했습니다.")
        self.verified_at = datetime.now(UTC)
        return rows

    async def fetch_track_reference(
        self, *, university_code: str, admission_year: int, track_name: str
    ):
        source_url = (
            f"{BASE_URL}/ucp/uvt/uni/univDetailSelection.do?menuId=PCUVTINF2000"
            f"&searchSyr={admission_year}&unvCd={university_code}"
        )
        response = await self._client.get(source_url)
        response.raise_for_status()
        parsed = parse_track_reference(response.text, track_name)
        return source_url, parsed

    async def fetch_programs(
        self, *, university_code: str, university_name: str, admission_year: int
    ) -> list[AdigaProgram]:
        csrf_token = await self._open_admission_session()
        response = await self._client.post(
            ADMISSION_LIST_URL,
            headers={"X-CSRF-TOKEN": csrf_token, "X-Requested-With": "XMLHttpRequest"},
            data={
                "pagination.currentPage": "1",
                "pagination.cntPerPage": "1000",
                "searchSyr": str(admission_year),
                "searchUnvCodeAllYn": "true",
                "searchTitle": university_name,
                "cnrtYear": str(datetime.now(UTC).year),
                "searchAdmissionFavorite": "N",
                "unvSeCd": "10",
                "menuId": "PCPRCINF2000",
                "sortOrder": "true",
            },
        )
        response.raise_for_status()
        self.verified_at = datetime.now(UTC)
        return [
            row for row in parse_programs(response.text) if row.university_code == university_code
        ]

    async def fetch_tracks(
        self, *, university_code: str, program_code: str, admission_year: int
    ) -> list[AdigaTrack]:
        csrf_token = await self._open_admission_session()
        response = await self._client.post(
            ADMISSION_TRACKS_URL,
            headers={"X-CSRF-TOKEN": csrf_token, "X-Requested-With": "XMLHttpRequest"},
            data={
                "pagination.currentPage": "1",
                "searchSyr": str(admission_year),
                "searchUnvCodeAllYn": "true",
                "cnrtYear": str(datetime.now(UTC).year),
                "searchAdmissionFavorite": "N",
                "unvSeCd": "10",
                "menuId": "PCPRCINF2000",
                "sortOrder": "true",
                "unvCd": university_code,
                "comScsbjtCd": program_code,
            },
        )
        response.raise_for_status()
        self.verified_at = datetime.now(UTC)
        return parse_tracks(
            response.text, university_code=university_code, program_code=program_code
        )

    async def fetch_university_statistics(
        self, *, university_code: str, admission_year: int
    ) -> AdigaUniversityStatistics:
        """대학 전체의 모집·지원, 경쟁률, 취업률, 전형분포 시계열을 읽는다.

        어디가의 차트 응답에는 화면 렌더링·관리용 필드도 섞여 있다. 그 원본을
        통째로 저장하지 않고, 수집 기준과 의미가 명확한 공개 통계만 보관한다.
        """
        response = await self._client.post(
            UNIVERSITY_STATISTICS_URL,
            headers={"X-Requested-With": "XMLHttpRequest"},
            data={"unvCd": university_code, "searchSyr": str(admission_year)},
        )
        response.raise_for_status()
        try:
            raw = response.json()
        except ValueError as error:
            raise AdigaSourceError("대입정보포털의 대학 통계 응답을 읽지 못했습니다.") from error
        if not isinstance(raw, dict):
            raise AdigaSourceError("대입정보포털의 대학 통계 형식이 올바르지 않습니다.")

        def source_rows(key: str) -> list[dict[str, object]]:
            value = raw.get(key)
            if not isinstance(value, list):
                return []
            return [row for row in value if isinstance(row, dict)]

        def as_int(value: object) -> int | None:
            try:
                return int(str(value)) if value not in (None, "") else None
            except ValueError:
                return None

        def as_float(value: object) -> float | None:
            try:
                return float(str(value)) if value not in (None, "") else None
            except ValueError:
                return None

        def as_text(value: object) -> str | None:
            text = str(value).strip() if value is not None else ""
            return text or None

        self.verified_at = datetime.now(UTC)
        return AdigaUniversityStatistics(
            source_url=UNIVERSITY_STATISTICS_URL,
            payload={
                "recruitment_and_applicants": [
                    {
                        "admission_year": as_int(row.get("syr")),
                        "admission_period": as_text(row.get("rcrrNm")),
                        "recruitment_count": as_int(row.get("rcmtNope")),
                        "applicant_count": as_int(row.get("applNmpr")),
                    }
                    for row in source_rows("uivRcnpRt")
                ],
                "selection_distribution": [
                    {
                        "admission_year": as_int(row.get("syr")),
                        "selection_type": as_text(row.get("slcnTypeCdNm")),
                        "recruitment_count": as_int(row.get("selctnRt")),
                    }
                    for row in source_rows("uivSelctnRt")
                ],
                "employment_rate": [
                    {
                        "year": as_int(str(row.get("syr") or "").replace("년도", "")),
                        "rate": as_float(row.get("empymnRt")),
                    }
                    for row in source_rows("uivEmpymnRt")
                ],
                "competition_rate": [
                    {
                        "admission_year": as_int(row.get("syr")),
                        "early_ratio": as_float(row.get("transCnrt")),
                        "regular_ratio": as_float(row.get("rdsnCnrt")),
                    }
                    for row in source_rows("uivCmpetRt")
                ],
            },
        )

    async def fetch_university_admission_guide(
        self, *, university_code: str, admission_year: int
    ) -> AdigaUniversityAdmissionGuide:
        """대학 단위 수시·정시 대입특징과 입시가이드를 가져온다.

        페이지에 나온 학년도와 요청 학년도가 같은지 파서가 확인한다. 내용이 없는
        페이지를 '정보 없음' 레코드로 적재하지 않아, 이후 가장 최근 정상 자료로
        안전하게 내려갈 수 있다.
        """
        source_url = (
            f"{UNIVERSITY_ADMISSION_GUIDE_URL}&searchSyr={admission_year}&unvCd={university_code}"
        )
        response = await self._client.get(source_url)
        response.raise_for_status()
        sections = parse_university_admission_guide(response.text)
        if not sections:
            raise AdigaSourceError("대입정보포털의 대학 입시가이드 내용을 읽지 못했습니다.")
        self.verified_at = datetime.now(UTC)
        return AdigaUniversityAdmissionGuide(source_url=source_url, sections=sections)

    async def fetch_program_references(
        self, *, university_code: str, admission_year: int
    ) -> list[AdigaProgramReference]:
        """대학의 설치학과 목록을 기준으로 이전 입시결과의 학과코드를 수집한다."""
        view_url = (
            f"{UNIVERSITY_SUBJECT_VIEW_URL}&searchSyr={admission_year}&unvCd={university_code}"
        )
        page = await self._client.get(view_url)
        page.raise_for_status()
        csrf_token = _csrf_token(page.text)
        response = await self._client.post(
            UNIVERSITY_SUBJECT_LIST_URL,
            headers={"X-CSRF-TOKEN": csrf_token, "X-Requested-With": "XMLHttpRequest"},
            data={
                "_csrf": csrf_token,
                "pagination.currentPage": "1",
                "pagination.cntPerPage": "1000",
                "searchSyr": str(admission_year),
                "syr": str(admission_year),
                "unvCd": university_code,
                "aftCd": "",
            },
        )
        response.raise_for_status()
        rows = parse_program_references(response.text)
        if not rows:
            raise AdigaSourceError("대입정보포털의 설치학과 목록을 읽지 못했습니다.")
        self.verified_at = datetime.now(UTC)
        return rows

    async def fetch_program_outcomes(
        self, *, university_code: str, reference_code: str, admission_year: int
    ) -> tuple[str, list[AdigaProgramOutcome]]:
        """학과·전형별 공개 입시결과를 읽는다.

        대학별로 비공개인 학과는 빈 목록으로 둔다. 빈 결과를 임의의 등급·컷으로
        대체하지 않기 위해, 응답 자체가 깨진 경우만 예외로 처리한다.
        """
        source_url = (
            f"{PROGRAM_OUTCOMES_URL}?ruCd={reference_code}&searchSyr={admission_year}"
            f"&unvCd={university_code}"
        )
        response = await self._client.get(source_url)
        response.raise_for_status()
        self.verified_at = datetime.now(UTC)
        return source_url, parse_program_outcomes(response.text)

    async def fetch_program_profile_sections(
        self, *, university_code: str, reference_code: str, admission_year: int
    ) -> tuple[str, list[dict[str, list[str] | str]]]:
        """학과 소개에서 학생의 탐색에 쓸 교육목표·교육과정·진로를 읽는다."""
        source_url = (
            f"{BASE_URL}/ucp/cls/uni/classUnivDetail.do?menuId=PCCLSINF2000"
            f"&searchSyr={admission_year}&unvCd={university_code}&ruCd={reference_code}"
        )
        response = await self._client.get(source_url)
        response.raise_for_status()
        self.verified_at = datetime.now(UTC)
        return source_url, parse_program_profile_sections(response.text)
