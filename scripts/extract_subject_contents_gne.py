"""경남교육 2024-008 과목 안내자료 PDF → app/services/subject_contents/*.json.

원본: 경상남도교육청 「2022 개정 교육과정 고등학교 보통교과 과목 안내자료」
(경남교육 2024-008, gne.go.kr 게시판 첨부 '전고등학교배부용' PDF). 교육부 고시
제2022-33호를 바탕으로 보통 교과와 과학·체육·예술 계열 선택 과목 231개를 과목당 한
페이지로 소개한다. PDF는 저장소에 넣지 않는다.

    uv run python scripts/extract_subject_contents_gne.py <PDF> \
        app/services/subject_contents/2022_gne_2024_008.json

한 페이지 = 과목 소개 문단(9pt) + '무엇을 배울까요?' 표. 표의 지식·이해 칸에서 영역
이름은 7~8.5pt(왼쪽 열), 내용 요소는 6.5pt다. 행과 구역은 표의 가로선으로 나눈다 —
글자 위치만으로는 영역 이름이 행 가운데에 오지 않는 표가 있어 요소가 옆 행으로 샌다.
"""

import json
import re
import sys
import unicodedata
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.subject_catalog import SUBJECTS, normalize  # noqa: E402

SOURCE = "경상남도교육청, 「2022 개정 교육과정 고등학교 보통교과 과목 안내자료」(경남교육 2024-008)"

# 표가 여러 열로 복잡하게 짜여 자동 추출이 뒤섞이는 과목은 원본 표를 보고 직접 옮긴다.
MANUAL_UNITS = {
    "2022:일본어": [
        "듣기·말하기: 음성적 특징(청·탁음, 장·단음, 요음, 박), 낱말·구·간단한 문장, "
        "인사·소개, 배려·의사 전달, 정보 교환, 행위 요구",
        "읽기: 히라가나와 가타카나, 학습용 한자, 간단한 문장·대화문·텍스트",
        "쓰기: 현대가나표기법, 현대 일본어 문법, 간단한 대화문·텍스트",
        "문화: 언어문화, 비언어 문화, 일본의 간략한 개관, 일상생활 문화, 대중문화",
    ],
}

# 이름을 소개 문장에서 뽑을 수 없는 페이지(짝 과목·첫 문장이 다른 말로 시작).
PAGE_OVERRIDES = {
    26: "공통국어1",
    27: "공통국어2",
    30: "문학",
    40: "공통수학1",
    41: "공통수학2",
    42: "기본수학1",
    43: "기본수학2",
    58: "공통영어1",
    59: "공통영어2",
    60: "기본영어1",
    61: "기본영어2",
    76: "한국사1",
    77: "한국사2",
    78: "통합사회1",
    79: "통합사회2",
    98: "기후변화와 지속가능한 세계",
    102: "통합과학1",
    103: "통합과학2",
    108: "생명과학",
    146: "기술·가정",
    288: "사진의 이해",
}


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def lines_of(page):
    """(x, y, 글자 크기, 글) — x는 홀짝 페이지 여백 차이를 지운 값('과목 소개' 기준)."""
    out = []
    for b in page.get_text("dict")["blocks"]:
        for line in b.get("lines", []):
            text = nfc("".join(s["text"] for s in line["spans"])).strip()
            if text:
                out.append(
                    [line["bbox"][0], line["bbox"][1], round(line["spans"][0]["size"], 1), text]
                )
    anchor = next((x for x, y, sz, t in out if t == "과목 소개"), None)
    if anchor is not None:
        for line in out:
            line[0] -= anchor - 96
    return [tuple(line) for line in out]


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=다\.)\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def summary_for(name: str, intro: str) -> str:
    sents = sentences(intro)
    # 짝 과목 페이지는 두 과목을 함께 소개한 뒤 "특히 ‘공통수학1’은…"으로 이 과목을 말한다.
    if name[-1].isdigit():
        specific = [s for s in sents if f"‘{name}’" in s and s is not sents[0]]
        if specific:
            return " ".join([sents[0], specific[0]])
    return " ".join(sents[:2])


def horizontal_lines(page):
    """표의 가로선 (y, x0). 행 구분선은 영역 열에서, 구역 구분선은 표 왼쪽 끝에서 시작한다."""
    out = set()
    for drawing in page.get_drawings():
        for item in drawing["items"]:
            if item[0] == "l":
                a, b = item[1], item[2]
                if abs(a.y - b.y) < 1 and abs(a.x - b.x) > 30:
                    out.add((round(a.y), round(min(a.x, b.x))))
            elif item[0] == "re":
                r = item[1]
                if r.height < 2 and r.width > 30:
                    out.add((round(r.y0), round(r.x0)))
    return sorted(out)


def units_for(page, lines) -> list[str]:
    header = next(((y, sz) for x, y, sz, t in lines if t == "범주"), None)
    if header is None:
        return []
    top = header[0] + header[1] * 1.2
    hlines = [(y, x0) for y, x0 in horizontal_lines(page) if y > top]
    if not hlines:
        return []
    left = min(x0 for _, x0 in hlines)
    sections = sorted(y for y, x0 in hlines if x0 <= left + 3)
    knowledge_end = sections[0]
    process_end = sections[1] if len(sections) > 1 else 10_000
    # 영역 열에서 시작하는 선만 행 구분이다. 요소 열 안의 보조선(영어의 '언어' 칸을
    # 세 줄로 나누는 선 등)은 한 영역 안의 구획일 뿐이다.
    inner = [(y, x0) for y, x0 in hlines if x0 > left + 10 and y < knowledge_end]
    area_left = min((x0 for _, x0 in inner), default=0)
    row_breaks = sorted(y for y, x0 in inner if x0 <= area_left + 3)

    def center(y, sz):
        return y + sz / 2

    labels = {"범주", "내용 요소", "지식·이해", "지식･이해", "과정·기능", "가치·태도"}
    areas, elems = [], []
    for x, y, sz, t in lines:
        c = center(y, sz)
        if not (top < c < knowledge_end) or t in labels:
            continue
        if sz >= 7.0 and 100 < x < 200:
            areas.append((c, x, t))
        elif sz <= 7.5 and x > 120:
            elems.append((c, x, sz, t))

    def row_of(c):
        return sum(1 for b in row_breaks if b < c)

    # 줄바꿈된 요소의 둘째 줄(7.5pt, 조금 들여 씀)은 같은 열 바로 위 요소에 붙인다.
    merged: list[list] = []
    for c, x, sz, t in sorted(elems, key=lambda e: (round(e[1] / 40), e[0])):
        prev = next((m for m in reversed(merged) if abs(m[1] - x) < 12), None)
        if sz > 6.5 and prev is not None and 0 < c - prev[0] < 20:
            prev[3] = f"{prev[3]} {t}"
            prev[0] = c
            continue
        merged.append([c, x, sz, t])

    area_rows: dict[int, list[tuple[float, str]]] = {}
    for c, _x, t in areas:
        area_rows.setdefault(row_of(c), []).append((c, t))
    elem_rows: dict[int, list[tuple[float, float, str]]] = {}
    for c, x, _sz, t in merged:
        elem_rows.setdefault(row_of(c), []).append((round(x / 40), c, t))

    result = []
    for row in sorted(set(area_rows) | set(elem_rows)):
        name = " ".join(t for _, t in sorted(area_rows.get(row, [])))
        items = [t for _, _, t in sorted(elem_rows.get(row, []))]
        text = ", ".join(items)
        result.append(f"{name}: {text}" if name and text else name or text)
    if not areas:
        # 영역 이름이 없는 과목(국어·한문 등)은 지식 칸이 몇 줄뿐이고, 무엇을 하는지는
        # 과정·기능 칸에 있다.
        skills = [
            t
            for x, y, sz, t in lines
            if sz <= 7.5
            and x > 120
            and knowledge_end < center(y, sz) < process_end
            and t not in labels
        ]
        if skills:
            result.append("활동: " + ", ".join(skills))
    cleaned = []
    for r in result:
        r = r.replace("\uf09f", "")
        r = re.sub(r"\[별표\s*\d+\]\s*", "", r)
        r = re.sub(r"\s+", " ", r).replace(" ,", ",").strip(" ,")
        if r:
            cleaned.append(r)
    return cleaned


def main(pdf: str, out: str) -> None:
    doc = pymupdf.open(pdf)
    by_name = {normalize(s.name): s for s in SUBJECTS if s.curriculum == "2022"}
    subjects, unmatched = {}, []
    for pno in range(doc.page_count):
        lines = lines_of(doc[pno])
        texts = [t for _, _, _, t in lines]
        if "과목 소개" not in texts:
            continue
        top = next(y for x, y, sz, t in lines if t == "과목 소개")
        bottom = next((y for x, y, sz, t in lines if t.startswith("무엇을 배울")), 10_000)
        # PDF의 줄 y값이 가끔 앞뒤로 어긋나 있어(글 순서는 맞음) 정렬하지 않고 문서 순서를 쓴다.
        intro = " ".join(t for x, y, sz, t in lines if sz == 9.0 and x < 100 and top < y < bottom)
        intro = re.sub(r"\s+", " ", intro)
        name = PAGE_OVERRIDES.get(pno + 1)
        if name is None:
            m = re.match(r"\s*[‘']([^’']+)[’']", intro)
            name = m.group(1) if m else None
        subject = by_name.get(normalize(name or ""))
        if subject is None:
            unmatched.append((pno + 1, name))
            continue
        subjects[subject.code] = {
            "summary": summary_for(subject.name, intro),
            "units": MANUAL_UNITS.get(subject.code) or units_for(doc[pno], lines),
            "page": pno + 1,
        }
    json.dump(
        {
            "source": SOURCE,
            "subjects": subjects,
        },
        open(out, "w", encoding="utf-8"),
        ensure_ascii=False,
        indent=2,
    )
    print("matched", len(subjects), "unmatched", unmatched)
    if unmatched:
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
