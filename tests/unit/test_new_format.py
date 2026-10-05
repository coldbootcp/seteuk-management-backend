"""새 서식(인적·학적사항 합본, 진로희망 표 없음, 봉사 한 칸 뭉침)에 대한 파서 회귀 테스트."""

from app.models.activity import ActivityCategory
from app.services.parser.career import parse_career_aspirations
from app.services.parser.changche import parse_changche_blocks
from app.services.parser.identity import parse_teacher_names
from app.services.parser.redact import sanitize_text

_CHANGCHE_TABLE = [
    ["학년", "창 의 적 체 험 활 동 상 황", None, None, None],
    [None, "영역", "시간", "특기사항", None],
    ["1", "동아리활동", "32", "", ""],
    [None, None, None, "실험 동아리에서 탱탱볼을 만들었다.", None],
    [None, "진로활동", "33", "희망분야", "나노공학 기술자"],
    [None, None, None, "진로탐색검사를 했다.", None],
    ["2", "진로활동", "43", "희망분야", "수학"],
]


def test_teacher_names_come_from_the_cover_table() -> None:
    table = [
        ["졸업 대장 번호", "2024-3282", None, None, None],
        ["구분\n학년", "학과", "반", "번호", "담임성명"],
        ["1", "", "2", "1", "박현주"],
        ["2", "", "9", "1", "박승하"],
    ]
    assert parse_teacher_names([table]) == ["박현주", "박승하"]


def test_sanitize_replaces_teacher_names() -> None:
    assert "박현주" not in sanitize_text("박현주 선생님께 배움", None, ["박현주"])


def test_changche_area_is_inherited_by_the_note_row_below() -> None:
    blocks = parse_changche_blocks([_CHANGCHE_TABLE])
    assert [b.category for b in blocks] == [ActivityCategory.CLUB, ActivityCategory.CAREER]
    # "희망분야" 칸은 서술 블록이 되지 않는다.
    assert all(b.text != "희망분야" for b in blocks)


def test_career_hope_is_read_from_changche_rows() -> None:
    items = parse_career_aspirations([_CHANGCHE_TABLE])
    assert [(i.grade, i.activity_name) for i in items] == [(1, "나노공학 기술자"), (2, "수학")]
