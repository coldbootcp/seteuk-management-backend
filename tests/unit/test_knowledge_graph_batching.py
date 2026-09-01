import json
import uuid

import pytest

import app.services.diagnosis.pipeline as pipeline
from app.models.activity import Activity
from app.schemas.diagnosis import KnowledgeGraphDraft


def _activity(grade: int, name: str) -> Activity:
    return Activity(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        grade=grade,
        semester=1,
        activity_category="과목세부특기사항",
        subject=None,
        activity_name=name,
        activity_type="report",
        description="",
        keywords=[],
    )


async def test_large_activity_set_is_split_into_adjacent_grade_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """활동이 임계값(120)을 넘으면 한 호출에 다 넣지 않고 인접 학년 쌍(1-2, 2-3)으로
    나눠 부르고, 겹치는 학년(2학년)에서 두 창 모두 같은 링크를 찾아도 병합 시
    하나로 합쳐져야 한다."""
    activities_by_grade = {
        grade: [_activity(grade, f"{grade}-{i}") for i in range(50)] for grade in (1, 2, 3)
    }

    batch_sizes: list[int] = []

    async def fake_call_structured(system_prompt, user_content, response_model):
        assert response_model is KnowledgeGraphDraft
        payload = json.loads(user_content)
        batch_sizes.append(len(payload["activities"]))
        # 두 창 모두에 등장하는 2학년의 첫 두 활동을 매번 링크로 낸다 — 실제로
        # 같은 두 활동이 두 번 발견되는 상황을 재현해 병합 로직을 검증한다.
        grade2_entries = [a for a in payload["activities"] if a["grade"] == 2][:2]
        if len(grade2_entries) < 2:
            return KnowledgeGraphDraft(links=[])
        return KnowledgeGraphDraft(
            links=[
                {
                    "from_index": grade2_entries[0]["index"],
                    "to_index": grade2_entries[1]["index"],
                    "link_type": "vertical",
                    "relation_label": "중복 확인용",
                }
            ]
        )

    monkeypatch.setattr(pipeline, "call_structured", fake_call_structured)

    links = await pipeline._write_knowledge_graph(activities_by_grade, interests={})

    # 150개(임계값 120 초과) → 인접 학년 쌍 2개(1-2, 2-3)로 나뉘어 두 번만 호출되고,
    # 각 호출은 100개(두 학년치)만 본다 — 150개를 한 번에 보내지 않았다는 증거.
    assert batch_sizes == [100, 100]

    # 두 창 모두 같은 두 활동(2학년의 처음 두 개)을 찾았지만, 병합 후에는 하나만
    # 남아야 한다.
    assert len(links) == 1
    linked_ids = {links[0].from_activity_id, links[0].to_activity_id}
    assert linked_ids == {activities_by_grade[2][0].id, activities_by_grade[2][1].id}


async def test_small_activity_set_uses_a_single_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """임계값 이하면 나누지 않고 한 번에 호출한다."""
    activities_by_grade = {1: [_activity(1, "활동1"), _activity(1, "활동2")]}

    calls = 0

    async def fake_call_structured(system_prompt, user_content, response_model):
        nonlocal calls
        calls += 1
        return KnowledgeGraphDraft(links=[])

    monkeypatch.setattr(pipeline, "call_structured", fake_call_structured)

    await pipeline._write_knowledge_graph(activities_by_grade, interests={})
    assert calls == 1
