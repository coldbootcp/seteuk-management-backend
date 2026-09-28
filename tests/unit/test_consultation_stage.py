from types import SimpleNamespace

from app.services.consultation_stage import (
    STAGE_FLOW,
    STAGE_GRADUATE_FIT,
    STAGE_SEMESTER_GOAL,
    STAGE_TOPICS,
    STAGE_WRAP_UP,
    compute_stage,
    remaining_periods,
    session_stage,
    validate_flow_nodes,
)


def _stage(**overrides) -> str:
    base = {
        "kind": "initial",
        "full_replan_confirmed": False,
        "has_flow": False,
        "flow_confirmed": False,
        "has_semester_goal": False,
        "has_draft_plan": False,
    }
    base.update(overrides)
    return compute_stage(**base)


def test_initial_consultation_starts_with_flow_and_narrows_down() -> None:
    assert _stage() == STAGE_FLOW
    # 흐름 초안만 있고 학생이 확정 버튼을 누르지 않았으면 아직 흐름 단계다.
    assert _stage(has_flow=True) == STAGE_FLOW
    assert _stage(has_flow=True, flow_confirmed=True) == STAGE_SEMESTER_GOAL
    assert (
        _stage(has_flow=True, flow_confirmed=True, has_semester_goal=True) == STAGE_TOPICS
    )
    assert (
        _stage(
            has_flow=True, flow_confirmed=True, has_semester_goal=True, has_draft_plan=True
        )
        == STAGE_WRAP_UP
    )


def test_old_style_draft_without_flow_cannot_skip_to_wrap_up() -> None:
    """예전 방식으로 흐름 없이 초안만 담긴 최초 상담은 흐름 단계로 돌아가야 한다."""
    assert _stage(has_semester_goal=True, has_draft_plan=True) == STAGE_FLOW


def test_semester_review_keeps_flow_unless_full_replan_confirmed() -> None:
    assert _stage(kind="semester_review") == STAGE_SEMESTER_GOAL
    assert _stage(kind="semester_review", full_replan_confirmed=True) == STAGE_FLOW


def test_graduate_fit_has_its_own_stage() -> None:
    assert _stage(kind="graduate_fit") == STAGE_GRADUATE_FIT


def test_session_stage_reads_session_attributes() -> None:
    session = SimpleNamespace(
        kind="initial",
        full_replan_confirmed_at=None,
        draft_flow={"nodes": []},
        flow_confirmed_at="2026-09-27",
        semester_goal=None,
        draft_plan=None,
    )
    assert session_stage(session) == STAGE_SEMESTER_GOAL


def test_remaining_periods() -> None:
    assert remaining_periods(1, 1) == [(1, 1), (1, 2), (2, 1), (2, 2), (3, 1), (3, 2)]
    assert remaining_periods(2, 2) == [(2, 2), (3, 1), (3, 2)]
    assert remaining_periods(3, 2) == [(3, 2)]


def _node(grade: int, semester: int, **extra) -> dict:
    return {
        "grade": grade,
        "semester": semester,
        "narrative_stage": "분화",
        "title": f"{grade}-{semester} 방향",
        "objective": "설명",
        **extra,
    }


def test_flow_keeps_only_remaining_semesters_in_order() -> None:
    nodes, error = validate_flow_nodes(
        [_node(3, 2), _node(1, 1), _node(3, 1), _node(2, 2)], 2, 2
    )
    assert error is None
    assert [(n["grade"], n["semester"]) for n in nodes] == [(2, 2), (3, 1), (3, 2)]


def test_flow_rejects_missing_semesters() -> None:
    nodes, error = validate_flow_nodes([_node(3, 1), _node(3, 2)], 2, 2)
    assert nodes is None
    assert "2학년 2학기" in error


def test_flow_requires_title_and_objective() -> None:
    nodes, error = validate_flow_nodes([_node(3, 2, title="  ")], 3, 2)
    assert nodes is None
    assert "title" in error


def test_flow_repairs_unknown_stage_name_and_cleans_lists() -> None:
    nodes, error = validate_flow_nodes(
        [_node(3, 2, narrative_stage="엉뚱한 단계", candidate_subjects=["수학", " ", 3])], 3, 2
    )
    assert error is None
    assert nodes[0]["narrative_stage"] == "종합"
    assert nodes[0]["candidate_subjects"] == ["수학"]


def test_flow_rejects_non_list() -> None:
    nodes, error = validate_flow_nodes(None, 1, 1)
    assert nodes is None and error
