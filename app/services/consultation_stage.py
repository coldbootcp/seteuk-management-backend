"""상담 진행 단계 — "3개년 흐름 → 이번 학기 목표 → 구체 주제 → 마무리".

상담 챗봇이 이번 학기 이야기부터 꺼내고 3개년 흐름은 알아서 정해 버리던 문제를
막기 위해, 단계를 세션에 저장된 사실만으로 계산한다. 프롬프트는 단계별로 할 일을
부탁하고, 도구 핸들러는 앞 단계가 끝나지 않았으면 다음 단계 저장을 거부한다
("프롬프트는 부탁, 코드가 보증").

이 모듈은 DB·LLM에 의존하지 않는 순수 함수만 둔다 — 단계 판정 규칙을 단위
테스트로 바로 확인할 수 있게 하기 위해서다.
"""

from typing import Any

STAGE_FLOW = "flow"
STAGE_SEMESTER_GOAL = "semester_goal"
STAGE_TOPICS = "topics"
STAGE_WRAP_UP = "wrap_up"
STAGE_GRADUATE_FIT = "graduate_fit"

STAGE_ORDER = [STAGE_FLOW, STAGE_SEMESTER_GOAL, STAGE_TOPICS, STAGE_WRAP_UP]

STAGE_LABELS = {
    STAGE_FLOW: "3개년 흐름 조율",
    STAGE_SEMESTER_GOAL: "이번 학기 목표 합의",
    STAGE_TOPICS: "구체 탐구 주제 정하기",
    STAGE_WRAP_UP: "초안 확인과 마무리",
    STAGE_GRADUATE_FIT: "목표 학과 적합성 상담",
}

# 3개년 흐름의 서사 단계 이름. roadmap/templates.py의 NARRATIVE_STAGES와 같은 순서.
NARRATIVE_STAGE_NAMES = ["탐색", "기초", "연결", "분화", "독립 탐구", "종합"]


def period_index(grade: int, semester: int) -> int:
    return (grade - 1) * 2 + (semester - 1)


def remaining_periods(target_grade: int, target_semester: int) -> list[tuple[int, int]]:
    """현재 학기부터 3학년 2학기까지 — 3개년 흐름에서 새로 그릴 수 있는 학기들."""
    start = period_index(target_grade, target_semester)
    return [(i // 2 + 1, i % 2 + 1) for i in range(max(0, start), 6)]


def needs_flow(kind: str, full_replan_confirmed: bool) -> bool:
    """이 상담이 3개년 흐름을 새로 합의해야 하는가.

    최초 상담은 항상 그렇다. 학기말 재평가는 기존 흐름을 유지하는 것이 기본이라
    이 단계를 건너뛰고, 진로 전환 등으로 전체 재설계에 학생이 명시 동의한 경우에만
    다시 흐름부터 세운다.
    """
    if kind == "initial":
        return True
    if kind == "semester_review":
        return full_replan_confirmed
    return False


def compute_stage(
    *,
    kind: str,
    full_replan_confirmed: bool,
    has_flow: bool,
    flow_confirmed: bool,
    has_semester_goal: bool,
    has_draft_plan: bool,
) -> str:
    if kind == "graduate_fit":
        return STAGE_GRADUATE_FIT
    if needs_flow(kind, full_replan_confirmed) and not (has_flow and flow_confirmed):
        return STAGE_FLOW
    if not has_semester_goal:
        return STAGE_SEMESTER_GOAL
    if not has_draft_plan:
        return STAGE_TOPICS
    return STAGE_WRAP_UP


def session_stage(session: Any) -> str:
    """ConsultationSession(또는 같은 속성을 가진 객체)의 현재 단계."""
    return compute_stage(
        kind=session.kind,
        full_replan_confirmed=session.full_replan_confirmed_at is not None,
        has_flow=session.draft_flow is not None,
        flow_confirmed=session.flow_confirmed_at is not None,
        has_semester_goal=session.semester_goal is not None,
        has_draft_plan=session.draft_plan is not None,
    )


def validate_flow_nodes(
    nodes: Any, target_grade: int, target_semester: int
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """propose_three_year_flow가 보낸 마디를 검사해 정규화한다.

    모델은 **현재 학기부터 3학년 2학기까지** 남은 학기만 그린다. 지나간 학기에
    새 계획을 만드는 실수를 모델에 맡기지 않고 입력 형태 자체로 막는다.
    반환: (정규화된 마디 목록, 오류 메시지) — 둘 중 하나만 채워진다.
    """
    expected = remaining_periods(target_grade, target_semester)
    if not isinstance(nodes, list) or not nodes:
        return None, "nodes에 현재 학기부터 3학년 2학기까지의 흐름을 채워주세요"

    by_period: dict[tuple[int, int], dict[str, Any]] = {}
    for raw in nodes:
        if not isinstance(raw, dict):
            return None, "nodes의 각 항목은 객체여야 합니다"
        try:
            period = (int(raw.get("grade")), int(raw.get("semester")))
        except (TypeError, ValueError):
            return None, "각 마디에 grade와 semester를 숫자로 채워주세요"
        if period not in expected:
            # 지나간 학기나 범위 밖 학기는 흐름 초안에 넣지 않는다.
            continue
        title = str(raw.get("title") or "").strip()
        objective = str(raw.get("objective") or "").strip()
        if not title or not objective:
            return None, f"{period[0]}학년 {period[1]}학기 마디에 title과 objective를 채워주세요"
        stage = str(raw.get("narrative_stage") or "").strip()
        if stage not in NARRATIVE_STAGE_NAMES:
            stage = NARRATIVE_STAGE_NAMES[period_index(*period)]
        by_period[period] = {
            "grade": period[0],
            "semester": period[1],
            "narrative_stage": stage,
            "title": title,
            "objective": objective,
            "candidate_subjects": _clean_strings(raw.get("candidate_subjects")),
            "competency_goals": _clean_strings(raw.get("competency_goals")),
        }

    missing = [p for p in expected if p not in by_period]
    if missing:
        labels = ", ".join(f"{g}학년 {s}학기" for g, s in missing)
        return None, f"다음 학기의 흐름이 빠졌습니다: {labels}"
    return [by_period[p] for p in expected], None


def _clean_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if isinstance(v, str) and v.strip()]
