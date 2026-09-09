import uuid

from app.models.roadmap import MatchType, RoadmapNode
from app.services.roadmap.reconciliation import judge


def _node(**kw) -> RoadmapNode:
    defaults = dict(
        id=uuid.uuid4(),
        roadmap_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        order_index=0,
        grade=2,
        semester=1,
        narrative_stage="연결",
        title="원리와 실제 사례를 근거로 설명",
        objective="교과 원리와 실제 사례가 이어지는 과정을 비교합니다.",
        candidate_subjects=["물리학", "수학", "정보"],
        competency_goals=["정량 분석", "모형 해석"],
        status="active",
    )
    return RoadmapNode(**{**defaults, **kw})


def test_no_active_node_is_unclassifiable_not_a_failure() -> None:
    """로드맵이 없거나 활성 노드가 없다고 해서 활동이 잘못된 것은 아니다."""
    verdict = judge(
        activity_text="아무 활동", activity_subject="국어", node=None, career_terms=[]
    )
    assert verdict.match_type == MatchType.UNCLASSIFIABLE.value
    assert "독립 기록" in verdict.rationale


def test_activity_on_the_node_topic_and_subject_matches() -> None:
    verdict = judge(
        activity_text=(
            "물리학 시간에 배운 원리를 실제 사례와 비교해 정량 분석하고 모형 해석까지 "
            "정리한 보고서"
        ),
        activity_subject="물리학",
        node=_node(),
        career_terms=["반도체"],
    )
    assert verdict.match_type == MatchType.MATCH.value
    assert verdict.confidence >= 72


def test_loosely_related_activity_is_partial_not_match() -> None:
    """조금 걸치는 활동을 MATCH로 올리면 노드가 충족되지 않았는데 다음으로 넘어간다."""
    verdict = judge(
        activity_text="물리학 관련 짧은 감상문",
        activity_subject="물리학",
        node=_node(),
        career_terms=[],
    )
    assert verdict.match_type == MatchType.PARTIAL_MATCH.value


def test_unrelated_activity_diverges_without_calling_it_a_mistake() -> None:
    """로드맵 밖 활동은 진로가 바뀌고 있다는 신호일 수도, 그냥 좋은 별개 활동일 수도
    있다. 이탈로 단정하지 않는 문구여야 한다."""
    verdict = judge(
        activity_text="교내 합창대회 준비",
        activity_subject="음악",
        node=_node(),
        career_terms=["반도체"],
    )
    assert verdict.match_type == MatchType.DIVERGE.value
    assert "단정하지 않습니다" in verdict.rationale


def test_career_signal_comes_from_the_student_not_a_fixed_domain() -> None:
    """원본은 "반도체·트랜지스터·공정…"을 하드코딩했다. 백엔드는 학생이 답한 진로
    어휘를 신호로 써야 하므로, 같은 활동이라도 학생의 진로에 따라 판정이 갈려야 한다.

    노드 주제와 살짝 겹치는(문턱 바로 아래) 활동을 써서 신호의 유무가 실제로
    결과를 바꾸는지 본다.
    """
    text = "해양 생태 자료를 분석해 정리함"

    marine = judge(
        activity_text=text, activity_subject="생명과학", node=_node(), career_terms=["해양"]
    )
    semiconductor = judge(
        activity_text=text, activity_subject="생명과학", node=_node(), career_terms=["반도체"]
    )

    # 해양을 지망하는 학생에게는 진로 신호가 잡혀 문턱을 넘고,
    assert marine.match_type == MatchType.PARTIAL_MATCH.value
    # 반도체를 지망하는 학생에게는 같은 활동이 노드와도 진로와도 멀다.
    assert semiconductor.match_type == MatchType.DIVERGE.value


def test_a_career_relevant_activity_off_the_node_topic_still_diverges() -> None:
    """진로에 맞는 활동이라도 지금 노드의 주제를 건드리지 않으면 그 노드를 충족한
    것은 아니다 — 진로 신호 하나로 문턱을 넘겨 주면 노드가 헐겁게 완료된다."""
    verdict = judge(
        activity_text="해양 쓰레기 수거 봉사에 참여함",
        activity_subject="봉사",
        node=_node(),
        career_terms=["해양"],
    )
    assert verdict.match_type == MatchType.DIVERGE.value
