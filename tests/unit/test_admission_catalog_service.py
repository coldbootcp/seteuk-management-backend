from app.services.adiga_catalog_source import AdigaTrack


def test_same_display_name_from_two_source_codes_is_deduplicated() -> None:
    rows = [
        AdigaTrack("one", "기타 > 부모 모두 외국인", "기타", "수시"),
        AdigaTrack("two", "기타 > 부모 모두 외국인", "기타", "수시"),
    ]
    assert len({row.name: row for row in rows}) == 1
