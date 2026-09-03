"""활동↔로드맵 정합 판정.

활동을 저장할 때마다 그 활동이 현재 활성 노드의 목표를 충족했는지 판정하고, 이유·조치·
신뢰도를 남긴다(D-2). 판정은 덮어쓰지 않고 쌓기만 한다 — 나중에 "왜 그렇게 판단했나"를
되짚을 수 있어야 하기 때문이다.

`MISS`는 여기서 나오지 않는다. 활동을 저장할 때가 아니라 학기 체크포인트에 완료 활동이
없을 때 생기는 시간 기반 이벤트라, `run_semester_checkpoint`가 따로 만든다.
"""

from dataclasses import dataclass

from app.models.roadmap import MatchType, RoadmapNode
from app.services.korean_text import overlap_count


@dataclass(frozen=True)
class Verdict:
    match_type: str
    rationale: str
    action: str
    confidence: int


def judge(
    *,
    activity_text: str,
    activity_subject: str,
    node: RoadmapNode | None,
    career_terms: list[str],
) -> Verdict:
    """순수 함수 — DB를 건드리지 않아 단독으로 검증할 수 있다.

    `career_terms`는 원본 프로토타입에서 "반도체·다이오드·트랜지스터·공정…"으로
    하드코딩돼 있던 자리를 대신한다. 백엔드는 특정 파일럿 도메인에 묶이면 안 되므로,
    그 신호를 **학생 자신이 답한 진로 어휘**(관심 키워드·진로 희망·목표 학과)에서
    가져온다. 반도체를 지망하는 학생에게는 여전히 반도체 단어가 신호가 되고, 다른
    진로의 학생에게는 그 진로의 단어가 신호가 된다.
    """
    if node is None:
        return Verdict(
            match_type=MatchType.UNCLASSIFIABLE.value,
            rationale="현재 활성 로드맵 노드가 없어 활동을 독립 기록으로 저장했습니다.",
            action="활동 저장 후 로드맵 검토 요청",
            confidence=45,
        )

    node_text = " ".join(
        [node.title, node.objective, *node.candidate_subjects, *node.competency_goals]
    )
    overlap = overlap_count(activity_text, node_text)

    lowered = activity_text.lower()
    career_signal = any(term and term.lower() in lowered for term in career_terms)
    subject_match = any(
        subject
        and activity_subject
        and (subject in activity_subject or activity_subject in subject)
        for subject in node.candidate_subjects
    )

    score = overlap * 2 + (2 if career_signal else 0) + (2 if subject_match else 0)

    if score >= 6:
        return Verdict(
            match_type=MatchType.MATCH.value,
            rationale=(
                f"활동의 교과·개념·산출물이 활성 노드 '{node.title}'의 목표와 직접 "
                "연결됩니다."
            ),
            action="현재 노드 완료 및 다음 노드 활성화",
            confidence=min(95, 72 + score * 3),
        )
    if score >= 3:
        goals = "·".join(node.competency_goals) or node.title
        return Verdict(
            match_type=MatchType.PARTIAL_MATCH.value,
            rationale=(
                f"활동이 활성 노드와 일부 연결되지만 '{goals}' 목표를 모두 충족하지는 "
                "않습니다."
            ),
            action="부분 충족으로 기록하고 후속 보완 활동 제안",
            confidence=68,
        )
    return Verdict(
        match_type=MatchType.DIVERGE.value,
        # 이탈로 단정하지 않는 것이 중요하다. 로드맵 밖 활동이 진로가 바뀌고 있다는
        # 신호일 수도 있고, 그냥 좋은 별개 활동일 수도 있다.
        rationale=(
            "현재 활성 노드와 직접 연결되는 교과·개념 근거가 적습니다. 유의미한 별도 "
            "활동일 수 있으므로 이탈로 단정하지 않습니다."
        ),
        action="로드맵 밖 활동으로 저장하고 학생 의도 확인",
        confidence=61,
    )
