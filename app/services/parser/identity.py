"""인적사항에서 학생의 성명을 읽는다.

학적사항에서 입학 연도를 읽는 것(enrollment.py)과 같은 자세다 — 추론이 아니라
문서가 밝힌 사실을 그대로 옮긴다. 인적사항은 보통 이렇게 적혀 있다.

    성명 : 홍길동   성별 : 남   주민등록번호 : ******-*******

공식 export는 정렬을 위해 글자 사이를 띄우거나("성 명"), 구분자(":")를 넣기도
빼기도 한다. 그래서 라벨은 느슨하게 맞추되, 값은 성명 뒤에 곧바로 붙는 다른
항목(성별·주민등록번호 등)이나 줄바꿈에서 끊는다.
"""

import re

# "성명"(또는 "성 명") 뒤의 값을 잡는다. 값은 한글 이름이며, 뒤에 붙는 다른
# 라벨(성별·생년월일·주민등록번호 등)이나 공백 2칸 이상/줄바꿈에서 끊어 과잉
# 매칭을 막는다. 한글 성명은 보통 2~5자다.
_NAME_PATTERN = re.compile(
    r"성\s*명\s*[:：]?\s*([가-힣]{2,5})",
)


def parse_student_name(section_text: str) -> str | None:
    """인적사항에 적힌 학생 성명. 없으면 None.

    파서가 성명 값을 확실히 읽을 때만 돌려준다 — 애매하면 이름을 지어내느니
    None을 주어, 화면이 사용자에게 직접 입력받게 한다.
    """
    match = _NAME_PATTERN.search(section_text)
    if match is None:
        return None
    name = match.group(1).strip()
    return name or None


def parse_teacher_names(tables: list[list[list[str | None]]]) -> list[str]:
    """표지 표("학년/학과/반/번호/담임성명")의 담임 이름들.

    담임 이름은 개인정보 가리기(redact)와 LLM 전송 전 정리(sanitize)에서 학생 이름처럼 다룬다.
    다른 교사 이름은 문서가 이름이라고 표시하지 않아 찾을 수 없다.
    """
    names: list[str] = []
    for table in tables:
        for row in table[:3]:
            header = ["".join((cell or "").split()) for cell in row]
            idx = next((i for i, c in enumerate(header) if "담임" in c and "성명" in c), None)
            if idx is None:
                continue
            for body in table[table.index(row) + 1 :]:
                if idx < len(body):
                    value = "".join((body[idx] or "").split())
                    if re.fullmatch(r"[가-힣]{2,5}", value) and value not in names:
                        names.append(value)
            break
    return names
