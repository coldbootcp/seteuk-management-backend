"""서울대학교 2027학년도 수시모집 안내를 학생용으로 구조화한 읽기 전용 자료.

원문: 2027학년도 대학 신입학생 수시모집 안내(2026. 5.)
https://admission.snu.ac.kr/webdata/admission/files/2027susi.pdf

전형·모집단위마다 달라지는 예외는 원문에서 확인한 경우에만 넣는다. 이 모듈은
다른 대학까지 일반화하지 않으며, 후속 수집기는 대학별 어댑터로 추가한다.
"""

from dataclasses import dataclass

SNU_2027_SUSI_URL = "https://admission.snu.ac.kr/webdata/admission/files/2027susi.pdf"


@dataclass(frozen=True)
class SnuTrackDetail:
    source_admission_year: int
    source_url: str
    selection_method: str
    eligibility: str
    document_evaluation: str
    interview: str
    csat_minimum: str
    schedule: list[str]
    subject_tip: str
    notes: list[str]
    sections: list[dict[str, str | list[str]]]


def _subject_tip(program_name: str) -> str:
    compact = program_name.replace(" ", "")
    engineering_words = ("공학", "컴퓨터", "조선", "건축", "산업", "에너지", "원자핵")
    if any(word in compact for word in engineering_words):
        return "공과대학은 수학(자연) 관련 제시문으로 전공적성과 학업역량을 평가합니다."
    if any(word in compact for word in ("물리", "천문", "화학", "생명", "지구", "수리", "통계")):
        return (
            "자연과학 계열은 모집단위별 물리·화학·생명과학·지구과학 또는 "
            "수학(자연) 제시문을 활용합니다."
        )
    if any(word in compact for word in ("의학", "치의", "수의", "간호")):
        return (
            "보건·의학 계열은 전공에 필요한 자질·적성·인성을 중심으로 "
            "상황/제시문 및 서류 기반 면접을 운영합니다."
        )
    return (
        "모집단위별 면접 제시문 분야와 출제 범위는 공식 모집안내의 면접·구술고사 표를 확인하세요."
    )


def _general_interview_section(program_name: str) -> tuple[str, list[str]]:
    compact = program_name.replace(" ", "")
    if any(
        word in compact for word in ("공학", "컴퓨터", "조선", "건축", "산업", "에너지", "원자핵")
    ):
        return (
            "수학(자연) 제시문을 활용해 전공적성과 학업역량을 평가합니다.",
            [
                "출제 범위: 수학, 수학Ⅰ, 수학Ⅱ, 확률과 통계, 미적분, 기하",
                "2026. 11. 27. 면접 및 구술고사 예정",
                "제시문을 읽고 풀이 과정과 판단 근거를 말로 설명하는 준비가 필요",
            ],
        )
    if "물리" in compact or "천문" in compact:
        return "물리학 관련 제시문으로 전공적성과 학업역량을 평가합니다.", [
            "출제 범위: 통합과학, 과학탐구실험, 물리학Ⅰ, 물리학Ⅱ",
            "제시문 속 현상을 교과 개념으로 설명하는 연습이 필요",
        ]
    if "화학" in compact:
        return "화학 관련 제시문으로 전공적성과 학업역량을 평가합니다.", [
            "출제 범위: 통합과학, 과학탐구실험, 화학Ⅰ, 화학Ⅱ",
            "반응·물질 구조·자료 해석을 근거와 함께 설명하는 연습이 필요",
        ]
    if "생명" in compact:
        return "생명과학 관련 제시문으로 전공적성과 학업역량을 평가합니다.", [
            "출제 범위: 통합과학, 과학탐구실험, 생명과학Ⅰ, 생명과학Ⅱ",
            "생명 현상을 자료와 연결해 설명하는 연습이 필요",
        ]
    return _subject_tip(program_name), [
        "모집단위별 제시문 분야와 출제 범위는 공식 모집안내의 면접·구술고사 표에 따름",
        "제출서류의 활동을 질문받았을 때 과정·판단·배움을 근거와 함께 설명할 수 있어야 함",
    ]


def get_snu_2027_susi_detail(*, track_name: str, program_name: str) -> SnuTrackDetail | None:
    """2027학년도 서울대 수시 전형의 확정 안내를 전형명에 맞춰 돌려준다."""
    compact = track_name.replace(" ", "")
    # 음악대학 일반전형은 실기평가와 별도 단계가 있어, 공통 일반전형 값으로
    # 덮어쓰지 않는다. 해당 전형은 세부 수집기를 별도로 추가해야 한다.
    if any(word in program_name for word in ("음악", "피아노", "관현악", "국악", "성악", "작곡")):
        return None
    if "수시모집지역균형" in compact:
        return SnuTrackDetail(
            source_admission_year=2027,
            source_url=SNU_2027_SUSI_URL,
            selection_method="1단계 서류평가 100%로 3배수 선발 · 2단계 1단계 성적 70% + 면접 30%",
            eligibility=(
                "소속 고등학교장 추천을 받은 2027년 2월 국내 고등학교 졸업예정자 · "
                "고교별 추천 2명 이내"
            ),
            document_evaluation=(
                "학생부 등 제출서류로 학업역량, 자기주도적 학업태도, "
                "전공 관심과 지적 호기심을 종합평가"
            ),
            interview=(
                "전 모집단위 서류 기반 면접(10분 내외). 의과대학은 "
                "상황/제시문+서류 기반 면접(60분 내외)"
            ),
            csat_minimum=(
                "전 모집단위 적용: 국어·수학·영어·탐구 중 3개 영역 등급 합 7 이내 "
                "(탐구는 2과목 평균)"
            ),
            schedule=[
                "원서접수 2026. 9. 7. 10:00 - 9. 9. 18:00",
                "면접 2026. 12. 4. 또는 12. 5. · 합격자 발표 12. 18. 이후",
            ],
            subject_tip=_subject_tip(program_name),
            notes=[
                "모집단위별 수능 응시영역기준을 반드시 준수",
                "사범대학은 교직적성·인성면접을 면접에 포함",
            ],
            sections=[
                {
                    "title": "지원 자격과 학교장 추천",
                    "description": "국내 고등학교 졸업예정자를 위한 학교장 추천 전형입니다.",
                    "items": [
                        "소속 고등학교장의 추천을 받은 2027년 2월 국내 고등학교 졸업예정자",
                        "고교별 추천 인원은 2명 이내",
                        "학교장추천전형 담당 교사가 원서접수 대행사에서 추천 여부를 입력",
                    ],
                },
                {
                    "title": "서류평가",
                    "description": "학생부 등 제출서류를 다수의 평가자가 다단계로 종합평가합니다.",
                    "items": [
                        "교과 이수·학습 활동의 성취수준과 학업역량",
                        "자기주도적 학습 경험에서 드러나는 지적 호기심·주도성·논리적 사고력",
                        "리더십·공동체 의식·책임감과 사회적 기여 가능성",
                        "이수 과목의 특성, 수업 내용, 학업 수행 내용, 이수자 수와 "
                        "교육환경을 함께 고려",
                    ],
                },
                {
                    "title": "면접",
                    "description": "서류를 토대로 기본 학업 소양을 확인하는 면접입니다.",
                    "items": [
                        "전 모집단위(의과대학 제외): 복수 면접위원, 10분 내외",
                        "의과대학: 상황/제시문 기반과 서류 기반 면접을 "
                        "복수 면접실에서 60분 내외 진행",
                        "사범대학: 교직적성·인성면접을 포함",
                    ],
                },
                {
                    "title": "수능최저와 수능 응시영역",
                    "description": (
                        "지역균형은 모든 모집단위에 수능최저와 응시영역기준이 적용됩니다."
                    ),
                    "items": [
                        "국어·수학·영어·탐구 중 3개 영역 등급 합 7 이내",
                        "탐구영역 등급은 2개 과목 등급 평균 반영",
                        "지원 모집단위에 맞는 수학 선택과목·탐구영역 기준을 별도로 충족해야 함",
                    ],
                },
            ],
        )
    if "수시모집일반전형" in compact:
        is_design = "디자인" in program_name
        interview_description, interview_items = _general_interview_section(program_name)
        return SnuTrackDetail(
            source_admission_year=2027,
            source_url=SNU_2027_SUSI_URL,
            selection_method=(
                "1단계 서류평가 100%로 2배수 선발 · 2단계 1단계 성적 100% + 면접 및 구술고사"
                if "사범" not in program_name
                else (
                    "1단계 서류평가 100%로 2배수 선발 · 2단계 1단계 성적 60% + "
                    "교직적성·인성면접 40%"
                )
            ),
            eligibility=(
                "고등학교 졸업자 또는 2027년 2월 졸업예정자 등 모집안내의 지원자격을 충족한 자"
            ),
            document_evaluation=(
                "학생부 등 제출서류로 학업역량·자기주도성·전공 관심·지적 호기심과 "
                "공동체 역량을 다단계 종합평가"
            ),
            interview="모집단위별 제시문 기반 면접 및 구술고사. 제출서류를 참고해 질문할 수 있음",
            csat_minimum=(
                "미술대학 디자인과만 적용: 국어·수학·영어·탐구 중 3개 영역 등급 합 7 이내"
                if is_design
                else "미술대학 디자인과를 제외한 전 모집단위는 수능최저 미적용"
            ),
            schedule=[
                "원서접수 2026. 9. 7. 10:00 - 9. 9. 18:00",
                "면접 및 구술고사 2026. 11. 27. 또는 11. 28. · 합격자 발표 12. 18. 이후",
            ],
            subject_tip=_subject_tip(program_name),
            notes=["제시문별 출제 범위는 고교 교육과정", "사범대학은 교직적성·인성면접을 병행"],
            sections=[
                {
                    "title": "전형 구조와 선발",
                    "description": (
                        "일반전형은 서류로 먼저 선발한 뒤, 면접 및 구술고사로 "
                        "학업역량과 사고력을 확인합니다."
                    ),
                    "items": [
                        "1단계: 서류평가 100%로 모집인원의 2배수 선발",
                        "2단계: 전 모집단위(미술·사범·음악 제외) 1단계 성적 100%와 "
                        "면접 및 구술고사로 선발",
                        "사범대학은 2단계에서 1단계 성적 60%와 교직적성·인성면접 40%를 반영",
                        "학교폭력 관련 기재사항은 정성평가해 서류평가에 반영",
                    ],
                },
                {
                    "title": "지원 자격과 제출 서류",
                    "description": (
                        "국내·외 고교 졸업(예정)자와 검정고시 합격자 등도 "
                        "지원 자격을 확인해 지원할 수 있습니다."
                    ),
                    "items": [
                        "고등학교 졸업자 또는 2027년 2월 졸업예정자, 또는 동등 학력 인정자",
                        "학생부 온라인 제공 동의자는 학생부를 별도 업로드하지 않음",
                        "온라인 제공이 불가능한 경우 학생부와 학교 교육과정 편성표 등을 업로드",
                        "외국 소재 고교 이력 등 해당자는 학생부 대체 서식과 "
                        "증빙서류를 요구할 수 있음",
                    ],
                },
                {
                    "title": "서류평가에서 보는 내용",
                    "description": (
                        "결과만이 아니라 고교 교육과정 안에서 무엇을 어떻게 깊게 "
                        "해 왔는지를 평가합니다."
                    ),
                    "items": [
                        "학업역량과 교과 학습의 성취수준",
                        "자기주도적 학업태도, 전공분야 관심, 지적 호기심",
                        "국어·영어·수학·사회·과학뿐 아니라 전 교과의 충실한 이수 여부",
                        "서울대 교과이수기준과 전공 연계 교과 이수 현황",
                        "리더십·공동체 의식·책임감 등 공동체 역량",
                    ],
                },
                {
                    "title": "이 학과의 면접·구술고사",
                    "description": interview_description,
                    "items": interview_items,
                },
                {
                    "title": "수능최저와 응시영역",
                    "description": (
                        "일반전형은 대부분 수능최저를 적용하지 않지만, 디자인과는 예외입니다."
                    ),
                    "items": [
                        "전 모집단위(미술대학 디자인과 제외)는 수능최저와 수능 응시영역기준 미적용",
                        "미술대학 디자인과: 국어·수학·영어·탐구 중 3개 영역 등급 합 7 이내",
                        "디자인과는 모집단위별 수능 응시영역기준도 준수해야 함",
                    ],
                },
                {
                    "title": "지원 전 마지막 확인",
                    "description": (
                        "일정·원서접수·원본서류 제출은 변동될 수 있어 "
                        "마감 전 공식 공지를 다시 확인해야 합니다."
                    ),
                    "items": [
                        "원서접수: 2026. 9. 7. 10:00부터 9. 9. 18:00까지",
                        "1단계 합격자 발표: 2026. 11. 20. 18:00 이후",
                        "면접 및 구술고사: 2026. 11. 27. 또는 11. 28.",
                        "합격자 발표: 2026. 12. 18. 18:00 이후",
                    ],
                },
            ],
        )
    return None
