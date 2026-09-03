"""3개년 서사 로드맵 템플릿.

프론트엔드 프로토타입(`docs/reference/product-harness.ts`의 `GENERIC_ROADMAP_STAGES`)
에서 옮겨 왔다. 통합 결정 D-1에 따라 로드맵은 평면 계획 목록이 아니라 **학년-학기마다
서사 단계가 있는 6개 마디**로 표현한다: 탐색 → 기초 → 연결 → 분화 → 독립 탐구 → 종합.

지금은 결정론적이다 — 템플릿을 학생의 관심 분야로 개인화할 뿐 LLM을 부르지 않는다.
원본 프로토타입도 같은 자리에 "실제 LLM 호출은 아직 연결하지 않았다"고 적어 두었다.
LLM 개인화를 얹는다면 P-3의 하네스 경계와 Reviewer를 거치는 별도 단계가 된다.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class NarrativeStage:
    grade: int
    semester: int
    stage: str
    title: str
    objective: str
    subjects: list[str] = field(default_factory=list)
    competencies: list[str] = field(default_factory=list)


# 참조 구현은 이 값이 "semiconductor-narrative-v1"이었지만, 실제 단계 정의는
# 도메인 중립(GENERIC_ROADMAP_STAGES)이다. 이름이 내용을 잘못 말하고 있어 고쳤다.
TEMPLATE_ID = "generic-narrative-v1"

NARRATIVE_STAGES: list[NarrativeStage] = [
    NarrativeStage(
        grade=1,
        semester=1,
        stage="탐색",
        title="관심 분야와 교과의 첫 연결 찾기",
        objective=(
            "관심 분야가 일상·산업·사회에서 쓰이는 방식을 살펴보고, 교과 개념과 "
            "연결되는 탐구 출발점을 찾습니다."
        ),
        subjects=["통합과학", "정보"],
        competencies=["진로 탐색", "기술 이해"],
    ),
    NarrativeStage(
        grade=1,
        semester=2,
        stage="기초",
        title="핵심 교과 개념을 관심 분야의 원리와 연결",
        objective=(
            "관심 분야의 핵심 원리를 교과 개념으로 설명하고, 사례·자료·비교 질문을 "
            "통해 이해를 구체화합니다."
        ),
        subjects=["통합과학", "수학", "정보"],
        competencies=["개념 연결", "기초 모델링"],
    ),
    NarrativeStage(
        grade=2,
        semester=1,
        stage="연결",
        title="원리와 실제 사례를 근거로 설명",
        objective=(
            "교과 원리와 실제 사례가 이어지는 과정을 비교하고, 근거를 바탕으로 자신의 "
            "설명을 만듭니다."
        ),
        subjects=["물리학", "수학", "정보"],
        competencies=["정량 분석", "모형 해석"],
    ),
    NarrativeStage(
        grade=2,
        semester=2,
        stage="분화",
        title="세부 관심축을 선택해 탐구 심화",
        objective=(
            "기존 기록과 관심을 바탕으로 한 세부 축을 선택하고, 비교·분석·해석을 통해 "
            "탐구를 심화합니다."
        ),
        subjects=["물리학", "화학", "수학과제 탐구", "정보"],
        competencies=["탐구 설계", "데이터 해석"],
    ),
    NarrativeStage(
        grade=3,
        semester=1,
        stage="독립 탐구",
        title="근거 기반의 독립 탐구로 확장",
        objective=(
            "공개 자료와 교과 지식을 활용해 가설·비교 기준·해석이 갖춰진 독립 탐구를 "
            "발전시킵니다."
        ),
        subjects=["전자기와 양자", "물질과 에너지", "융합과학 탐구"],
        competencies=["문제 해결", "근거 기반 결론"],
    ),
    NarrativeStage(
        grade=3,
        semester=2,
        stage="종합",
        title="한계와 사회적 영향까지 포함해 관점 종합",
        objective=(
            "이전 기록의 발전 과정을 정리하고, 관심 분야의 한계와 사회적 영향을 포함한 "
            "최종 관점을 만듭니다."
        ),
        subjects=["융합과학 탐구", "사회문제 탐구", "국어"],
        competencies=["비판적 사고", "서사 구성"],
    ),
]

# 이미 지나간 학기의 마디. 새로 계획할 것이 아니라 생기부에서 확인할 대상이다.
RETROSPECT_STAGE = "회고"
RETROSPECT_TITLE = "기존 활동 기록"
RETROSPECT_OBJECTIVE = "생기부 연동을 통해 과거 활동을 확인하세요."


def _has_final_consonant(word: str) -> bool:
    """마지막 글자에 받침이 있는지. 한글 음절은 (초성×21 + 중성)×28 + 종성으로
    이루어져 있어서, 28로 나눈 나머지가 0이 아니면 받침이 있다."""
    if not word:
        return False
    last = word[-1]
    if not ("\uac00" <= last <= "\ud7a3"):
        # 한글이 아니면(영문·숫자로 끝나는 관심 분야) 받침 없는 쪽으로 읽어 준다.
        return False
    return (ord(last) - 0xAC00) % 28 != 0


def with_particle(word: str, with_final: str, without_final: str) -> str:
    """받침에 맞는 조사를 붙인다 — "데이터분석과", "광소자와"."""
    return f"{word}{with_final if _has_final_consonant(word) else without_final}"


def active_index(grade: int, semester: int) -> int:
    """학생의 현재 학년-학기가 6개 마디 중 몇 번째인지. 범위를 벗어나면 양 끝으로 붙인다."""
    return max(0, min(len(NARRATIVE_STAGES) - 1, (grade - 1) * 2 + (semester - 1)))


def suggested_topics(focus: str, stage: NarrativeStage) -> list[dict[str, str]]:
    """한 학기에 제안할 탐구 주제 10개. core 4개는 그 학기에 남겨야 할 축이고,
    optional 6개는 학교 기회가 맞을 때 고르는 확장이다 — 학생이 전부 하는 것이
    아니라 골라 담는 목록이다."""
    subject = stage.subjects[0] if stage.subjects else "자율 탐구"
    competency = stage.competencies[0] if stage.competencies else "탐구 설계"
    start_month = 4 if stage.semester == 1 else 9

    topics: list[tuple[str, str, str]] = [
        (
            "core",
            f"{focus}의 핵심 개념과 실제 사례 연결",
            f"교과의 핵심 개념이 {focus}의 실제 사례에서 어떻게 쓰이는지 비교해 설명하는 "
            "주제입니다.",
        ),
        (
            "core",
            f"{focus}에서 {with_particle(competency, '을', '를')} 보여줄 수 있는 비교 질문",
            "조건이 다른 사례를 비교해 어떤 기준으로 판단해야 하는지 탐구하는 주제입니다.",
        ),
        (
            "core",
            f"{focus}의 작동 원리와 한계 함께 살피기",
            "기술 또는 현상이 잘 작동하는 조건과 한계를 함께 정리해 균형 잡힌 관점을 만드는 "
            "주제입니다.",
        ),
        (
            "core",
            f"{with_particle(focus, '과', '와')} 현재 교과의 연결 고리 찾기",
            f"현재 {subject}에서 배우는 개념을 출발점으로 진로 관심을 자연스럽게 연결하는 "
            "주제입니다.",
        ),
        (
            "optional",
            f"{focus} 관련 공개 자료의 해석 차이 비교",
            "같은 주제라도 자료마다 결론이 달라지는 이유와 신뢰할 근거를 살피는 확장 주제입니다.",
        ),
        (
            "optional",
            f"{with_particle(focus, '이', '가')} 해결하는 문제와 남는 문제",
            "기술의 장점만 소개하지 않고 해결되지 않은 문제를 함께 정의해 보는 주제입니다.",
        ),
        (
            "optional",
            f"{focus}의 사회·환경적 영향",
            "진로 관심을 사회, 환경, 윤리 관점과 연결해 판단 기준을 세워 보는 주제입니다.",
        ),
        (
            "optional",
            f"{with_particle(focus, '과', '와')} 인접 분야의 공통점과 차이",
            "인접 전공 또는 교과와 비교해 자신의 관심 분야를 더 구체화하는 주제입니다.",
        ),
        (
            "optional",
            f"{focus}의 핵심 용어를 학생 언어로 재구성",
            "어려운 개념을 정확하면서도 쉽게 설명할 수 있는지 점검하는 주제입니다.",
        ),
        (
            "optional",
            f"{focus}에서 이어질 다음 탐구 질문 만들기",
            "이번 학기에서 바로 실행하지 않아도 다음 학기 심화로 이어질 질문을 남기는 주제입니다.",
        ),
    ]

    return [
        {
            # 같은 달에 여러 주제가 몰리므로 순번을 함께 저장한다. 없으면 새로고침할
            # 때마다 목록 순서가 바뀐다.
            "order_index": index,
            # 주제가 학기 초부터 두 달에 걸쳐 퍼지도록 앞의 셋만 월을 밀고 나머지는
            # 같은 달에 둔다(원본 프로토타입과 같은 배치).
            "month_day": f"{start_month + min(index, 2):02d}-15",
            "category": "활동",
            "subject": subject,
            "priority": priority,
            "title": title,
            "description": description,
        }
        for index, (priority, title, description) in enumerate(topics)
    ]
