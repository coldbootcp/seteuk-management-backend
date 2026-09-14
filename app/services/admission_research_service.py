# ruff: noqa: E501
"""대학·단과대학·학과·전형 인사이트 제공자.

API 응답은 모든 대학에 동일한 카드 구조를 사용한다. 대학별 수집기는 이 모듈에
카드를 추가하기만 하면 되므로, 화면이나 개인 지원 카드의 구조를 바꾸지 않아도
다른 대학을 확장할 수 있다. 수치에는 반드시 적용 학년도와 원천을 붙인다.
"""

from dataclasses import dataclass

SNU_SUSI_URL = "https://admission.snu.ac.kr/webdata/admission/files/2027susi.pdf"
SNU_ENGINEERING_VISION_URL = "https://eng.snu.ac.kr/about/engineering/vision-and-ideal-talent"
SNU_ENGINEERING_AGENDA_URL = "https://eng.snu.ac.kr/about/engineering/core-agneda"
SNU_ARORI_URL = "https://snuarori.snu.ac.kr/highschool-life/freshman-life"
SNU_2025_RESULT_URL = (
    "https://storage.googleapis.com/cna-storage/BOARD_FILE/2025/01/30/"
    "e39cd405-87b4-490f-9192-4d31d6740194.pdf"
)


@dataclass(frozen=True)
class ResearchCard:
    title: str
    description: str
    items: list[str]
    source_label: str
    source_url: str
    source_admission_year: int | None = None
    is_service_interpretation: bool = False


def _engineering_cards(program_name: str, track_name: str) -> list[ResearchCard]:
    cards = [
        ResearchCard(
            title="서울공대가 내세우는 방향",
            description="서울공대는 공학 활동을 한 줄의 스펙이 아니라, 수월성·융합·창의가 드러나는 성장 과정으로 볼 근거가 있습니다.",
            items=[
                "비전: 수월·융합·창의의 학문공동체",
                "인재상: 수월·융합·창의의 글로벌 리더",
                "핵심 방향: 맞춤형 교육, 융합 기술생태계, 지속가능한 개방형 캠퍼스",
            ],
            source_label="서울대학교 공과대학 비전과 인재상",
            source_url=SNU_ENGINEERING_VISION_URL,
        ),
        ResearchCard(
            title="학생부에서 연결해 볼 역량",
            description="공식 평가기준과 공대 인재상을 학생 기록에 연결한 서비스의 해석입니다. 활동을 새로 만들라는 뜻이 아니라, 이미 한 활동에서 어떤 근거를 꺼낼지 정리하는 기준입니다.",
            items=[
                "수월: 어려운 교과 개념을 스스로 확장하고, 자료·계산·실험의 한계를 점검한 흔적",
                "융합: 공학 문제를 환경·안전·사회·경제 등 다른 관점과 연결해 본 흔적",
                "창의: 정답을 반복하기보다 문제를 새로 정의하고, 대안을 비교한 흔적",
                "공동체: 팀 활동에서 역할·의사결정·책임을 구체적으로 남긴 흔적",
            ],
            source_label="서울대 수시모집 안내 및 서울공대 인재상에 근거한 서비스 해석",
            source_url=SNU_SUSI_URL,
            source_admission_year=2027,
            is_service_interpretation=True,
        ),
        ResearchCard(
            title="학과 맞춤 준비 포인트",
            description=f"{program_name} 지원자는 일반적인 ‘공학 관심’보다 학과와 연결되는 교과 기반 설명을 준비하는 편이 좋습니다.",
            items=[
                "수학(자연) 제시문에서 사용한 개념·풀이 전략·검산 과정을 말로 설명하는 연습",
                "학생부의 탐구·프로젝트를 문제 인식 → 방법 선택 → 결과 해석 → 한계와 다음 질문 순서로 정리",
                "활동마다 이 학과를 택한 이유를 억지로 덧붙이지 말고, 실제 관심이 깊어진 계기를 분명히 기록",
            ],
            source_label="2027학년도 서울대 수시 일반전형 면접·구술고사 안내",
            source_url=SNU_SUSI_URL,
            source_admission_year=2027,
            is_service_interpretation=True,
        ),
    ]
    if "조선해양" in program_name and "수시모집일반전형" in track_name.replace(" ", ""):
        cards.insert(
            0,
            ResearchCard(
                title="확인 가능한 과거 입시 결과",
                description="과거 결과는 합격 보장선이 아닙니다. 서울대 학생부종합전형은 교과 성적만으로 선발하지 않으므로, 참고 지표로만 사용하세요.",
                items=[
                    "2025학년도 수시 일반전형 조선해양공학과: 모집 22명, 경쟁률 10.23:1",
                    "최종등록자 교과성적: 50% 컷 2.71등급, 70% 컷 3.48등급",
                    "충원 1명으로 공개됨",
                    "교과성적 컷은 서류·종합순위 자체의 컷이 아니라 대학 반영 방식으로 환산된 교과 지표임",
                ],
                source_label="2026학년도 대입전형자료집 Ⅲ의 2025학년도 결과",
                source_url=SNU_2025_RESULT_URL,
                source_admission_year=2025,
            ),
        )
    return cards


def get_admission_research(
    *, university_name: str, program_name: str, track_name: str
) -> list[ResearchCard]:
    """지원처에 맞는 카드만 반환한다. 미수집 대학은 빈 목록을 반환한다."""
    if university_name != "서울대학교":
        return []
    compact = program_name.replace(" ", "")
    if any(
        word in compact for word in ("공학", "컴퓨터", "조선", "건축", "산업", "에너지", "원자핵")
    ):
        return _engineering_cards(program_name, track_name)
    return [
        ResearchCard(
            title="서울대 학생부종합전형이 보는 과정",
            description="서울대는 학생부를 바탕으로 학업역량뿐 아니라 학업에 대한 노력과 의지, 성장 가능성을 종합적으로 평가한다고 안내합니다.",
            items=[
                "과목 선택과 학습 과정에서 드러나는 주도성",
                "관심을 질문·탐구·성찰로 발전시킨 흐름",
                "학교 교육과정 안에서 쌓은 학업·공동체 경험",
            ],
            source_label="서울대 입학정보 웹진 아로리 및 2027 수시모집 안내",
            source_url=SNU_ARORI_URL,
            source_admission_year=2027,
        )
    ]
