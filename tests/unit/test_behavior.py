from app.services.parser.behavior import parse_behavior_blocks

BEHAVIOR_TABLE_PAGE_1 = [
    ["학 년", "행동 특성 및 종합의견"],
    ["1", "따뜻한 품성으로 주변 친구들을 도움."],
    ["2", "신중하게 판단하고 행동하며 책임감이"],
]

BEHAVIOR_TABLE_PAGE_2 = [
    ["학 년", "행동 특성 및 종합의견"],
    ["2", "강함을 볼 수 있음."],
]


def test_parse_behavior_blocks_groups_by_grade() -> None:
    blocks = parse_behavior_blocks([BEHAVIOR_TABLE_PAGE_1, BEHAVIOR_TABLE_PAGE_2])

    by_grade = {b.grade: b.text for b in blocks}
    assert by_grade[1] == "따뜻한 품성으로 주변 친구들을 도움."


def test_parse_behavior_blocks_merges_text_split_across_page_break() -> None:
    blocks = parse_behavior_blocks([BEHAVIOR_TABLE_PAGE_1, BEHAVIOR_TABLE_PAGE_2])

    by_grade = {b.grade: b.text for b in blocks}
    assert by_grade[2] == "신중하게 판단하고 행동하며 책임감이 강함을 볼 수 있음."


def test_parse_behavior_blocks_ignores_unrelated_tables() -> None:
    unrelated = [["수상명", "등급"], ["대회", "금상"]]

    assert parse_behavior_blocks([unrelated]) == []
