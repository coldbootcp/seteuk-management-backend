from app.models.activity import ActivityCategory, ActivityType
from app.services.parser.career import parse_career_aspirations

CAREER_TABLE = [
    ["학 년", "진로 희망", "희망 사유"],
    ["1", "기계공학자", "로봇에 대한 관심을 바탕으로\n기계공학자를 꿈꾸게 됨."],
    ["2", "기계공학자", "학습한 이론이 응용되는 것에 흥미를 느낌."],
]


def test_parse_career_aspirations_reads_grade_and_reason() -> None:
    items = parse_career_aspirations([CAREER_TABLE])

    assert len(items) == 2
    assert items[0].grade == 1
    assert items[0].activity_category == ActivityCategory.CAREER
    assert items[0].activity_type == ActivityType.OTHER
    assert items[0].activity_name == "기계공학자"
    assert "기계공학자를 꿈꾸게" in items[0].description


def test_parse_career_aspirations_ignores_unrelated_tables() -> None:
    unrelated = [["수상명", "등급"], ["대회", "금상"]]

    assert parse_career_aspirations([unrelated]) == []
