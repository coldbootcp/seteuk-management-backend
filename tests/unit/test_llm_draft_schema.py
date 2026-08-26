from app.models.activity import ActivityType
from app.schemas.seteuk import LLMActivityDraft, LLMActivityDraftList


def test_unknown_activity_type_falls_back_to_other() -> None:
    # DeepSeek can return a value outside the prompt's enum (observed: "lecture",
    # "writing") despite being told the exact allowed set.
    draft = LLMActivityDraft(activity_name="특강 참여", activity_type="lecture", description="설명")

    assert draft.activity_type == ActivityType.OTHER


def test_known_activity_type_is_preserved() -> None:
    draft = LLMActivityDraft(activity_name="탐구보고서", activity_type="report", description="설명")

    assert draft.activity_type == ActivityType.REPORT


def test_draft_list_survives_one_invalid_activity_type_among_valid_ones() -> None:
    payload = {
        "items": [
            {"activity_name": "A", "activity_type": "report", "description": "d"},
            {"activity_name": "B", "activity_type": "writing", "description": "d"},
        ]
    }

    drafts = LLMActivityDraftList.model_validate(payload)

    assert drafts.items[0].activity_type == ActivityType.REPORT
    assert drafts.items[1].activity_type == ActivityType.OTHER
