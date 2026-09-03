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


async def test_lineage_pairs_are_dropped_even_when_the_llm_returns_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """이미 parent_activity_id로 이어진 쌍은 진로 사슬·계보 화면이 이미 다루므로
    그래프에 다시 올라오면 안 된다. 프롬프트로도 지시하지만 실제 DeepSeek 응답이
    이 지시를 무시하고 계보 쌍만 돌려주는 것이 관측됐으므로(그러면 그래프가
    계보의 중복이 되어 아무 정보도 더하지 못한다) 코드에서 확정적으로 걸러낸다."""
    root = _activity(1, "버스 데이터 정리")
    child = _activity(2, "회귀분석으로 확장")
    child.parent_activity_id = root.id
    unrelated = _activity(2, "등가속도 오차 분석")

    async def fake_call_structured(system_prompt, user_content, response_model):
        # LLM이 계보 쌍(1↔2)과 진짜 새 연결(2↔3)을 함께 돌려주는 상황.
        return KnowledgeGraphDraft(
            links=[
                {
                    "from_index": 1,
                    "to_index": 2,
                    "link_type": "vertical",
                    "relation_label": "계보 중복",
                },
                {
                    "from_index": 2,
                    "to_index": 1,
                    "link_type": "vertical",
                    "relation_label": "방향만 뒤집힌 중복",
                },
                {
                    "from_index": 2,
                    "to_index": 3,
                    "link_type": "horizontal",
                    "relation_label": "오차 개념 접목",
                },
            ]
        )

    monkeypatch.setattr(pipeline, "call_structured", fake_call_structured)

    links = await pipeline._write_knowledge_graph_batch([root, child, unrelated], {})

    assert [link.relation_label for link in links] == ["오차 개념 접목"]


async def test_duplicate_and_self_links_are_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    """같은 쌍을 방향만 바꿔 두 번 내거나 자기 자신을 가리키는 응답도 버린다."""
    a, b = _activity(1, "A"), _activity(2, "B")

    async def fake_call_structured(system_prompt, user_content, response_model):
        return KnowledgeGraphDraft(
            links=[
                {
                    "from_index": 1,
                    "to_index": 2,
                    "link_type": "vertical",
                    "relation_label": "진짜 연결",
                },
                {
                    "from_index": 2,
                    "to_index": 1,
                    "link_type": "vertical",
                    "relation_label": "같은 쌍 재등장",
                },
                {
                    "from_index": 1,
                    "to_index": 1,
                    "link_type": "vertical",
                    "relation_label": "자기 자신",
                },
            ]
        )

    monkeypatch.setattr(pipeline, "call_structured", fake_call_structured)

    links = await pipeline._write_knowledge_graph_batch([a, b], {})

    assert [link.relation_label for link in links] == ["진짜 연결"]


async def test_thread_entries_are_sorted_even_when_the_llm_returns_them_jumbled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """갈래는 "흐름"으로 읽히는 것이 전부라 순서가 어긋나면 의미가 무너진다.
    프롬프트가 학년-학기 순을 요구해도 실제 응답이 뒤섞여 오는 것을 관측했다."""
    from app.schemas.diagnosis import CareerThreadDraft

    draft = CareerThreadDraft(
        career_thread=[
            {
                "title": "갈래",
                "summary": "요약",
                "activity_indexes": [],
                "entries": [
                    {"grade": 2, "semester": 1, "type": "completed", "theme": "나중",
                     "source": "s", "connection": "c"},
                    {"grade": 1, "semester": None, "type": "completed", "theme": "학년단위",
                     "source": "s", "connection": "c"},
                    {"grade": 1, "semester": 2, "type": "completed", "theme": "먼저",
                     "source": "s", "connection": "c"},
                ],
            }
        ]
    )

    class _FakeDb:
        async def scalars(self, *a, **kw):
            return []

        async def execute(self, *a, **kw):
            return None

        async def delete(self, *a, **kw):
            return None

        def add(self, *a, **kw):
            return None

        async def flush(self):
            return None

    threads = await pipeline._persist_threads(_FakeDb(), uuid.uuid4(), draft, {})

    assert [e.theme for e in threads[0].entries] == ["학년단위", "먼저", "나중"]
