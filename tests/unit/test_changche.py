from app.models.activity import ActivityCategory
from app.services.parser.changche import parse_changche_blocks

CHANGCHE_TABLE = [
    ["학년", "창 의 적 체 험 활 동 상 황", None, None],
    [None, "영역", "시간", "특기사항"],
    ["1", "", "", "자율활동 특기사항 텍스트"],
    [None, "동아리활동", "43", "동아리활동 특기사항 텍스트"],
    [None, "봉사활동", "", ""],
    [None, "진로활동", "13", "진로활동 특기사항 텍스트"],
]


def test_parse_changche_blocks_reads_category_from_area_column() -> None:
    blocks = parse_changche_blocks([CHANGCHE_TABLE])

    assert len(blocks) == 3
    assert blocks[0].grade == 1
    assert blocks[0].category == ActivityCategory.AUTONOMOUS
    assert blocks[1].category == ActivityCategory.CLUB
    assert blocks[2].category == ActivityCategory.CAREER


def test_parse_changche_blocks_skips_volunteer_and_empty_rows() -> None:
    blocks = parse_changche_blocks([CHANGCHE_TABLE])

    assert all(b.category != ActivityCategory.CAREER or "진로" in b.text for b in blocks)
    assert not any("봉사" == b.text for b in blocks)


def test_parse_changche_blocks_ignores_unrelated_tables() -> None:
    unrelated = [["수상명", "등급"], ["대회", "금상"]]

    assert parse_changche_blocks([unrelated]) == []
