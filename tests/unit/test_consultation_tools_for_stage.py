from types import SimpleNamespace

from app.services.chat.consultation_tools import tools_for_stage


def _session(**overrides) -> SimpleNamespace:
    base = {
        "kind": "initial",
        "full_replan_confirmed_at": None,
        "draft_flow": None,
        "flow_confirmed_at": None,
        "semester_goal": None,
        "draft_plan": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _names(session: SimpleNamespace) -> list[str]:
    return [spec["function"]["name"] for spec in tools_for_stage(session)]


def test_flow_stage_only_offers_the_flow_tool() -> None:
    """흐름이 확정되기 전에는 이번 학기 목표·주제를 저장할 수단 자체를 보여 주지 않는다."""
    assert _names(_session()) == ["propose_three_year_flow"]
    assert _names(_session(draft_flow={"nodes": []})) == ["propose_three_year_flow"]


def test_later_stages_add_one_step_at_a_time() -> None:
    confirmed = {"draft_flow": {"nodes": []}, "flow_confirmed_at": "t"}
    assert _names(_session(**confirmed)) == ["set_semester_goal", "propose_three_year_flow"]
    assert _names(_session(**confirmed, semester_goal={"title": "g"})) == [
        "propose_draft_plan",
        "set_semester_goal",
        "propose_three_year_flow",
    ]
    wrap_up = _names(_session(**confirmed, semester_goal={"title": "g"}, draft_plan={}))
    assert wrap_up[0] == "signal_ready_to_conclude"


def test_semester_review_keeps_flow_tool_hidden_until_full_replan_is_confirmed() -> None:
    review = _names(_session(kind="semester_review"))
    assert review == ["set_semester_goal", "propose_full_replan_exception"]

    replan = _names(_session(kind="semester_review", full_replan_confirmed_at="t"))
    assert replan == ["propose_three_year_flow"]
