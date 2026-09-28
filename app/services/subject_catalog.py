"""고등학교 과목 카탈로그 — 학생이 과목을 "고르게" 하기 위한 정본.

학생이 과목명을 자유롭게 타이핑하면 "수학1", "수Ⅰ", "수학 Ⅰ"처럼 같은 과목이 여러
이름으로 흩어져, 과목 데이터(교과군·선택 구분·학점)와 1:1로 이어지지 않는다. 그래서
온보딩·시간표에서 과목은 이 카탈로그의 후보 중에서만 고르고, 기록에는 `subject_code`를
남긴다. 학교가 자체 개설한 과목(학교지정과목·공동교육과정)은 우리가 교육과정을 알 수
없으므로 "기타"로 직접 입력하게 하고 `subject_code` 없이 저장한다.

DB 테이블이 아니라 코드에 둔 이유: 과목 목록은 교육부 고시가 바뀔 때만 바뀌는
참조 데이터라 코드 리뷰·버전 관리를 거치는 편이 안전하고, 시드 마이그레이션을 따로
관리할 필요가 없다. 기록 쪽은 코드 문자열(`2022:대수`)만 저장하므로 나중에 테이블로
옮겨도 기존 기록이 그대로 이어진다.

출처
- 2022 개정 보통 교과: 고교학점제 지원센터 "과목 소개 — 2022개정 교육과정"
  (교육부 고시 제2022-33호 [별책 4] 총론 표5와 대조).
- 2022 개정 과학·체육·예술 계열: 같은 고시의 특수 목적 고등학교 선택 과목 표(총론 <표 6>).
  2022에는 외국어·국제 계열 선택 과목이 없다.
- 2015 개정 보통 교과: 고교학점제 지원센터 "과목 소개 — 2015개정 교육과정".
- 2022 예술 계열은 경남교육 2024-008 과목 안내자료와 대조했다(`subject_contents` 참고).
- `verified=False`인 묶음(2015 예술 계열, 2015 전문 교과Ⅰ)은 공식 페이지를 직접 확인하지
  못해 교육부 고시 제2015-74호의 전문 교과Ⅰ 편제로 알려진 이름을 옮겼다. 학생이 목록에서
  못 찾으면 "기타"로 입력할 수 있으므로 치명적이지는 않지만, 공식 표와 한 번 대조할 것.
- 직업계고 전문 교과(NCS 기반, 17개 교과군·수백 과목)는 넣지 않았다 — 이 서비스의
  대상(학생부종합전형 준비)과 거리가 멀고, 필요한 학생은 "기타"로 입력한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

CURRICULUM_2015 = "2015"
CURRICULUM_2022 = "2022"
# 2025학년도 고1(입학생)부터 2022 개정 교육과정이 적용된다.
FIRST_2022_FRESHMAN_YEAR = 2025

COMMON = "공통"
GENERAL = "일반선택"
CAREER = "진로선택"
FUSION = "융합선택"
SPECIALIZED = "전문교과"


@dataclass(frozen=True)
class Subject:
    code: str
    name: str
    curriculum: str
    # 교과(군): 국어·수학·영어·사회·한국사·과학·체육·예술·기술·가정/정보·제2외국어·한문·교양
    group: str
    category: str  # 공통/일반선택/진로선택/융합선택/전문교과
    default_units: int
    track: str | None = None  # 전문 교과의 계열(과학 계열 등). 보통 교과는 None.
    verified: bool = True
    aliases: tuple[str, ...] = field(default=())


# ── 데이터 ────────────────────────────────────────────────────────────────
# (교과군, 선택 구분, 과목명 목록, 계열) 묶음. 학점(단위)은 교육과정별 기본값을 쓰고
# 예외만 _UNIT_OVERRIDES로 덮는다.

_LANGS = ["독일어", "프랑스어", "스페인어", "중국어", "일본어", "러시아어", "아랍어", "베트남어"]
_LANG_CULTURE_2022 = {
    "독일어": "독일어권 문화",
    "프랑스어": "프랑스어권 문화",
    "스페인어": "스페인어권 문화",
    "중국어": "중국 문화",
    "일본어": "일본 문화",
    "러시아어": "러시아 문화",
    "아랍어": "아랍 문화",
    "베트남어": "베트남 문화",
}

_GROUPS_2022: list[tuple[str, str, list[str], str | None, bool]] = [
    ("국어", COMMON, ["공통국어1", "공통국어2"], None, True),
    ("국어", GENERAL, ["화법과 언어", "독서와 작문", "문학"], None, True),
    ("국어", CAREER, ["주제 탐구 독서", "문학과 영상", "직무 의사소통"], None, True),
    ("국어", FUSION, ["독서 토론과 글쓰기", "매체 의사소통", "언어생활 탐구"], None, True),
    ("수학", COMMON, ["공통수학1", "공통수학2", "기본수학1", "기본수학2"], None, True),
    ("수학", GENERAL, ["대수", "미적분Ⅰ", "확률과 통계"], None, True),
    ("수학", CAREER, ["기하", "미적분Ⅱ", "경제 수학", "인공지능 수학", "직무 수학"], None, True),
    ("수학", FUSION, ["수학과 문화", "실용 통계", "수학과제 탐구"], None, True),
    ("영어", COMMON, ["공통영어1", "공통영어2", "기본영어1", "기본영어2"], None, True),
    ("영어", GENERAL, ["영어Ⅰ", "영어Ⅱ", "영어 독해와 작문"], None, True),
    (
        "영어",
        CAREER,
        ["영미 문학 읽기", "영어 발표와 토론", "심화 영어", "심화 영어 독해와 작문", "직무 영어"],
        None,
        True,
    ),
    ("영어", FUSION, ["실생활 영어 회화", "미디어 영어", "세계 문화와 영어"], None, True),
    ("한국사", COMMON, ["한국사1", "한국사2"], None, True),
    ("사회", COMMON, ["통합사회1", "통합사회2"], None, True),
    ("사회", GENERAL, ["세계시민과 지리", "세계사", "사회와 문화", "현대사회와 윤리"], None, True),
    (
        "사회",
        CAREER,
        [
            "한국지리 탐구", "도시의 미래 탐구", "동아시아 역사 기행", "정치", "법과 사회",
            "경제", "윤리와 사상", "인문학과 윤리", "국제 관계의 이해",
        ],
        None,
        True,
    ),
    (
        "사회",
        FUSION,
        [
            "여행지리", "역사로 탐구하는 현대 세계", "사회문제 탐구", "금융과 경제생활",
            "윤리문제 탐구", "기후변화와 지속가능한 세계",
        ],
        None,
        True,
    ),
    ("과학", COMMON, ["통합과학1", "통합과학2", "과학탐구실험1", "과학탐구실험2"], None, True),
    ("과학", GENERAL, ["물리학", "화학", "생명과학", "지구과학"], None, True),
    (
        "과학",
        CAREER,
        [
            "역학과 에너지", "전자기와 양자", "물질과 에너지", "화학 반응의 세계",
            "세포와 물질대사", "생물의 유전", "지구시스템과학", "행성우주과학",
        ],
        None,
        True,
    ),
    ("과학", FUSION, ["과학의 역사와 문화", "기후변화와 환경생태", "융합과학 탐구"], None, True),
    ("체육", GENERAL, ["체육1", "체육2"], None, True),
    ("체육", CAREER, ["운동과 건강", "스포츠 문화", "스포츠 과학"], None, True),
    ("체육", FUSION, ["스포츠 생활1", "스포츠 생활2"], None, True),
    ("예술", GENERAL, ["음악", "미술", "연극"], None, True),
    (
        "예술",
        CAREER,
        ["음악 연주와 창작", "음악 감상과 비평", "미술 창작", "미술 감상과 비평"],
        None,
        True,
    ),
    ("예술", FUSION, ["음악과 미디어", "미술과 매체"], None, True),
    ("기술·가정/정보", GENERAL, ["기술·가정", "정보"], None, True),
    (
        "기술·가정/정보",
        CAREER,
        ["로봇과 공학세계", "생활과학 탐구", "인공지능 기초", "데이터 과학"],
        None,
        True,
    ),
    (
        "기술·가정/정보",
        FUSION,
        [
            "창의 공학 설계", "지식 재산 일반", "생애 설계와 자립", "아동발달과 부모",
            "소프트웨어와 생활",
        ],
        None,
        True,
    ),
    ("제2외국어", GENERAL, list(_LANGS), None, True),
    (
        "제2외국어",
        CAREER,
        [f"{lang} 회화" for lang in _LANGS] + [f"심화 {lang}" for lang in _LANGS],
        None,
        True,
    ),
    ("제2외국어", FUSION, [_LANG_CULTURE_2022[lang] for lang in _LANGS], None, True),
    ("한문", GENERAL, ["한문"], None, True),
    ("한문", CAREER, ["한문 고전 읽기"], None, True),
    ("한문", FUSION, ["언어생활과 한자"], None, True),
    ("교양", GENERAL, ["진로와 직업", "생태와 환경"], None, True),
    (
        "교양",
        CAREER,
        ["인간과 철학", "논리와 사고", "인간과 심리", "교육의 이해", "삶과 종교", "보건"],
        None,
        True,
    ),
    ("교양", FUSION, ["인간과 경제활동", "논술"], None, True),
    # ── 특수 목적 고등학교 계열 선택 과목
    (
        "수학",
        SPECIALIZED,
        ["전문 수학", "이산 수학", "고급 대수", "고급 미적분", "고급 기하"],
        "과학 계열",
        True,
    ),
    (
        "과학",
        SPECIALIZED,
        [
            "고급 물리학", "고급 화학", "고급 생명과학", "고급 지구과학", "과학과제 연구",
            "물리학 실험", "화학 실험", "생명과학 실험", "지구과학 실험",
        ],
        "과학 계열",
        True,
    ),
    ("기술·가정/정보", SPECIALIZED, ["정보과학"], "과학 계열", True),
    (
        "체육",
        SPECIALIZED,
        [
            "스포츠 개론", "육상", "체조", "수상 스포츠", "스포츠 교육", "기초 체육 전공 실기",
            "심화 체육 전공 실기", "고급 체육 전공 실기", "스포츠 경기 체력", "스포츠 생리의학",
            "스포츠 경기 기술", "스포츠 경기 분석", "스포츠 행정 및 경영",
        ],
        "체육 계열",
        True,
    ),
    # 2022 개정 총론 <표 6>: 특수 목적 고등학교 선택 과목은 과학·체육·예술 계열뿐이다.
    # 2015의 외국어·국제 계열 과목은 보통 교과(심화 영어, 심화 독일어, 국제 관계의 이해 등)로
    # 흡수됐다.
]

# 2022 예술 계열 전문 교과 — 경남교육 2024-008 과목 안내자료(교육부 고시 제2022-33호 기반)의
# 과목 페이지 48개와 대조했다.
_ARTS_TRACK_2022 = [
    "음악 이론", "음악사", "시창·청음", "음악 전공 실기", "합창·합주", "음악 공연 실습",
    "음악과 문화",
    "미술 이론", "드로잉", "미술사", "미술 전공 실기", "조형 탐구", "미술 매체 탐구",
    "미술과 사회",
    "무용의 이해", "무용과 몸", "무용 기초 실기", "무용 전공 실기", "안무", "무용 제작 실습",
    "무용 감상과 비평", "무용과 매체",
    "문예 창작의 이해", "문장론", "문학 감상과 비평", "시 창작", "소설 창작", "극 창작",
    "문학과 매체",
    "연극과 몸", "연극과 말", "연기", "무대 미술과 기술", "연극 제작 실습", "연극 감상과 비평",
    "연극과 삶",
    "영화의 이해", "촬영·조명", "편집·사운드", "영화 제작 실습", "영화 감상과 비평", "영화와 삶",
    "사진의 이해", "사진 촬영", "사진 표현 기법", "영상 제작의 이해", "사진 감상과 비평",
    "사진과 삶",
]
_GROUPS_2022.append(("예술", SPECIALIZED, _ARTS_TRACK_2022, "예술 계열", True))

# 2015 예술 계열 전문 교과 — 공식 표를 직접 확인하지 못했다(모듈 docstring 참고).
_ARTS_TRACK_2015 = [
    "음악 이론", "음악사", "시창·청음", "음악 전공 실기", "합창·합주", "음악 공연 실습",
    "미술 이론", "미술사", "드로잉", "미술 전공 실기", "조형 탐구",
    "무용의 이해", "무용과 몸", "무용 기초 실기", "무용 전공 실기", "안무", "무용과 매체",
    "무용 음악 실습", "무용 제작 실습", "무용 감상과 비평",
    "문예 창작 입문", "문학 개론", "문장론", "문학과 매체", "고전문학 감상", "현대문학 감상",
    "시 창작", "소설 창작", "극 창작",
    "연극의 이해", "연극과 몸", "연극과 말", "연기", "무대 미술과 기술", "연극 제작 실습",
    "연극 감상과 비평",
    "영화의 이해", "촬영·조명", "편집·사운드", "영화 제작 실습", "영화 감상과 비평",
    "사진의 이해", "사진 촬영", "사진 표현 기법", "영상 제작의 이해", "사진 감상과 비평",
]


_GROUPS_2015: list[tuple[str, str, list[str], str | None, bool]] = [
    ("국어", COMMON, ["국어"], None, True),
    ("국어", GENERAL, ["화법과 작문", "독서", "언어와 매체", "문학"], None, True),
    ("국어", CAREER, ["실용 국어", "심화 국어", "고전 읽기"], None, True),
    ("수학", COMMON, ["수학"], None, True),
    ("수학", GENERAL, ["수학Ⅰ", "수학Ⅱ", "미적분", "확률과 통계"], None, True),
    (
        "수학",
        CAREER,
        ["기본 수학", "실용 수학", "인공지능 수학", "기하", "경제 수학", "수학과제 탐구"],
        None,
        True,
    ),
    ("영어", COMMON, ["영어"], None, True),
    ("영어", GENERAL, ["영어 회화", "영어Ⅰ", "영어 독해와 작문", "영어Ⅱ"], None, True),
    (
        "영어",
        CAREER,
        ["기본 영어", "실용 영어", "영어권 문화", "진로 영어", "영미 문학 읽기"],
        None,
        True,
    ),
    ("한국사", COMMON, ["한국사"], None, True),
    ("사회", COMMON, ["통합사회"], None, True),
    (
        "사회",
        GENERAL,
        [
            "한국지리", "세계지리", "세계사", "동아시아사", "경제", "정치와 법", "사회·문화",
            "생활과 윤리", "윤리와 사상",
        ],
        None,
        True,
    ),
    ("사회", CAREER, ["여행지리", "사회문제 탐구", "고전과 윤리"], None, True),
    ("과학", COMMON, ["통합과학", "과학탐구실험"], None, True),
    ("과학", GENERAL, ["물리학Ⅰ", "화학Ⅰ", "생명과학Ⅰ", "지구과학Ⅰ"], None, True),
    (
        "과학",
        CAREER,
        ["물리학Ⅱ", "화학Ⅱ", "생명과학Ⅱ", "지구과학Ⅱ", "과학사", "생활과 과학", "융합과학"],
        None,
        True,
    ),
    ("체육", GENERAL, ["체육", "운동과 건강"], None, True),
    ("체육", CAREER, ["스포츠 생활", "체육 탐구"], None, True),
    ("예술", GENERAL, ["음악", "미술", "연극"], None, True),
    (
        "예술",
        CAREER,
        ["음악 연주", "음악 감상과 비평", "미술 창작", "미술 감상과 비평"],
        None,
        True,
    ),
    ("기술·가정/정보", GENERAL, ["기술·가정", "정보"], None, True),
    (
        "기술·가정/정보",
        CAREER,
        [
            "농업 생명 과학", "공학 일반", "창의 경영", "해양 문화와 기술", "가정과학",
            "지식 재산 일반", "인공지능 기초",
        ],
        None,
        True,
    ),
    ("제2외국어", GENERAL, [f"{lang}Ⅰ" for lang in _LANGS], None, True),
    ("제2외국어", CAREER, [f"{lang}Ⅱ" for lang in _LANGS], None, True),
    ("한문", GENERAL, ["한문Ⅰ"], None, True),
    ("한문", CAREER, ["한문Ⅱ"], None, True),
    (
        "교양",
        GENERAL,
        [
            "철학", "논리학", "심리학", "교육학", "종교학", "진로와 직업", "보건", "환경",
            "실용 경제", "논술",
        ],
        None,
        True,
    ),
    # ── 전문 교과Ⅰ(특수 목적 고등학교) — 공식 페이지를 직접 확인하지 못했다.
    ("수학", SPECIALIZED, ["고급 수학Ⅰ", "고급 수학Ⅱ"], "과학 계열", False),
    (
        "과학",
        SPECIALIZED,
        [
            "고급 물리학", "고급 화학", "고급 생명과학", "고급 지구과학", "물리학 실험",
            "화학 실험", "생명과학 실험", "지구과학 실험", "융합과학 탐구", "과학과제 연구",
            "생태와 환경",
        ],
        "과학 계열",
        False,
    ),
    ("기술·가정/정보", SPECIALIZED, ["정보과학"], "과학 계열", False),
    (
        "체육",
        SPECIALIZED,
        [
            "스포츠 개론", "체육과 진로 탐구", "체육 지도법", "육상 운동", "체조 운동", "수상 운동",
            "개인·대인 운동", "단체 운동", "체육 전공 실기 기초", "체육 전공 실기 심화",
            "체육 전공 실기 응용", "스포츠 경기 실습", "스포츠 경기 분석", "스포츠 교육",
            "스포츠 생리의학", "스포츠 행정 및 경영",
        ],
        "체육 계열",
        False,
    ),
    (
        "예술",
        SPECIALIZED,
        [n for n in _ARTS_TRACK_2015 if n != "음악 공연 실습"],
        "예술 계열",
        False,
    ),
    (
        "영어",
        SPECIALIZED,
        [
            "심화 영어 회화Ⅰ", "심화 영어 회화Ⅱ", "심화 영어Ⅰ", "심화 영어Ⅱ",
            "심화 영어 독해Ⅰ", "심화 영어 독해Ⅱ", "심화 영어 작문Ⅰ", "심화 영어 작문Ⅱ",
        ],
        "외국어 계열",
        False,
    ),
    (
        "제2외국어",
        SPECIALIZED,
        [
            name
            for lang in _LANGS
            for name in (
                f"전공 기초 {lang}", f"{lang} 회화Ⅰ", f"{lang} 회화Ⅱ",
                f"{lang} 독해와 작문Ⅰ", f"{lang} 독해와 작문Ⅱ", _LANG_CULTURE_2022[lang],
            )
        ],
        "외국어 계열",
        False,
    ),
    (
        "사회",
        SPECIALIZED,
        [
            "국제 정치", "국제 경제", "국제법", "지역 이해", "한국 사회의 이해", "비교 문화",
            "세계 문제와 미래 사회", "국제 관계와 국제기구", "현대 세계의 변화", "사회 탐구 방법",
            "사회과제 연구",
        ],
        "국제 계열",
        False,
    ),
]

# 교육과정별 기본 학점(2022)·단위(2015). 학교마다 ±로 조정하므로 기본값일 뿐이다.
_DEFAULT_UNITS = {CURRICULUM_2022: 4, CURRICULUM_2015: 5}
_UNIT_OVERRIDES = {
    (CURRICULUM_2022, "과학탐구실험1"): 1,
    (CURRICULUM_2022, "과학탐구실험2"): 1,
    (CURRICULUM_2022, "한국사1"): 3,
    (CURRICULUM_2022, "한국사2"): 3,
    (CURRICULUM_2015, "과학탐구실험"): 2,
    (CURRICULUM_2015, "한국사"): 3,
    (CURRICULUM_2015, "국어"): 4,
    (CURRICULUM_2015, "수학"): 4,
    (CURRICULUM_2015, "영어"): 4,
    (CURRICULUM_2015, "통합사회"): 4,
    (CURRICULUM_2015, "통합과학"): 4,
}

# 학생들이 흔히 쓰는 줄임말. 검색에서 이 말로도 과목이 걸리게 한다.
_MANUAL_ALIASES: dict[str, tuple[str, ...]] = {
    "수학Ⅰ": ("수1",),
    "수학Ⅱ": ("수2",),
    # 2022 개정의 대수·미적분Ⅰ은 2015 개정의 수학Ⅰ·수학Ⅱ 자리다 — 옛 이름으로 찾는 학생이 많다.
    "대수": ("수1", "수학1"),
    "미적분": ("미적",),
    "미적분Ⅰ": ("미적1", "미적", "수2", "수학2"),
    "미적분Ⅱ": ("미적2",),
    "확률과 통계": ("확통",),
    "물리학Ⅰ": ("물1",),
    "물리학Ⅱ": ("물2",),
    "화학Ⅰ": ("화1",),
    "화학Ⅱ": ("화2",),
    "생명과학Ⅰ": ("생1", "생명1"),
    "생명과학Ⅱ": ("생2", "생명2"),
    "지구과학Ⅰ": ("지1", "지구1"),
    "지구과학Ⅱ": ("지2", "지구2"),
    "통합사회": ("통사",),
    "통합사회1": ("통사1", "통사"),
    "통합사회2": ("통사2", "통사"),
    "통합과학": ("통과",),
    "통합과학1": ("통과1", "통과"),
    "통합과학2": ("통과2", "통과"),
    "과학탐구실험": ("과탐실",),
    "과학탐구실험1": ("과탐실1", "과탐실"),
    "과학탐구실험2": ("과탐실2", "과탐실"),
    "기술·가정": ("기가", "기술가정"),
    "사회·문화": ("사문", "사회문화"),
    "사회와 문화": ("사문",),
    "생활과 윤리": ("생윤",),
    "윤리와 사상": ("윤사",),
    "한국지리": ("한지",),
    "세계지리": ("세지",),
    "동아시아사": ("동사",),
    "정치와 법": ("정법",),
    "언어와 매체": ("언매",),
    "화법과 작문": ("화작",),
    "화법과 언어": ("화언",),
    "독서와 작문": ("독작",),
    "영어 독해와 작문": ("영독작",),
    "인공지능 수학": ("인수", "AI 수학"),
    "인공지능 기초": ("AI 기초",),
    "공통국어1": ("국어1",),
    "공통국어2": ("국어2",),
    "공통수학1": ("수학1",),
    "공통수학2": ("수학2",),
    "공통영어1": ("영어1",),
    "공통영어2": ("영어2",),
}

_ROMAN = str.maketrans({"Ⅰ": "1", "Ⅱ": "2", "Ⅲ": "3"})


def normalize(text: str) -> str:
    """검색 비교용: 공백·가운뎃점 제거, 로마 숫자·라틴 I를 아라비아 숫자로, 소문자로."""
    value = (text or "").translate(_ROMAN)
    value = re.sub(r"(?<=[가-힣])II\b", "2", value)
    value = re.sub(r"(?<=[가-힣])I\b", "1", value)
    return re.sub(r"[\s·ㆍ․∙.\-_]", "", value).lower()


def _build() -> list[Subject]:
    subjects: list[Subject] = []
    for curriculum, groups in ((CURRICULUM_2022, _GROUPS_2022), (CURRICULUM_2015, _GROUPS_2015)):
        seen: set[str] = set()
        for group, category, names, track, verified in groups:
            for name in names:
                if name in seen:
                    # 같은 이름이 보통 교과와 전문 교과에 모두 있으면(예: 2015 생태와 환경은
                    # 교양이 아니라 과학 계열) 먼저 나온 쪽을 정본으로 쓴다.
                    continue
                seen.add(name)
                units = _UNIT_OVERRIDES.get((curriculum, name), _DEFAULT_UNITS[curriculum])
                subjects.append(
                    Subject(
                        code=f"{curriculum}:{name}",
                        name=name,
                        curriculum=curriculum,
                        group=group,
                        category=category,
                        default_units=units,
                        track=track,
                        verified=verified,
                        aliases=_MANUAL_ALIASES.get(name, ()),
                    )
                )
    return subjects


SUBJECTS: list[Subject] = _build()
_BY_CODE: dict[str, Subject] = {s.code: s for s in SUBJECTS}
_CATEGORY_ORDER = {COMMON: 0, GENERAL: 1, CAREER: 2, FUSION: 3, SPECIALIZED: 4}


def get_subject(code: str | None) -> Subject | None:
    return _BY_CODE.get(code or "")


def curriculum_for_freshman_year(freshman_year: int) -> str:
    return CURRICULUM_2022 if freshman_year >= FIRST_2022_FRESHMAN_YEAR else CURRICULUM_2015


def academic_year_of(value: date) -> int:
    return value.year if value.month >= 3 else value.year - 1


def curriculum_for_student(
    freshman_year: int | None, current_grade: int | None, today: date | None = None
) -> str:
    """학생이 적용받는 교육과정. 입학 학년도가 있으면 그것으로, 없으면 지금 학년에서
    거꾸로 센다. 둘 다 없으면 지금 신입생 기준(2022)."""
    if freshman_year:
        return curriculum_for_freshman_year(freshman_year)
    if current_grade:
        year = academic_year_of(today or date.today()) - current_grade + 1
        return curriculum_for_freshman_year(year)
    return CURRICULUM_2022


def search(query: str, curriculum: str | None = None, limit: int = 20) -> list[Subject]:
    """과목 검색. "수"를 치면 공통수학1, 수학Ⅰ…이 나오고, "수1"·"물1" 같은 줄임말도 걸린다.

    줄임말이 정확히 일치하는 과목을 맨 앞에 두고, 그다음은 이름에 검색어가 들어간 과목을
    공통 → 일반 → 진로 → 융합 → 전문 교과 순(학생이 실제로 많이 듣는 순)으로 보여 준다.
    같은 구분 안에서는 이름이 검색어로 시작하는 것, 짧은 것이 먼저다.
    """
    q = normalize(query)
    if not q:
        return []
    scored: list[tuple[int, int, int, int, str, Subject]] = []
    for subject in SUBJECTS:
        if curriculum is not None and subject.curriculum != curriculum:
            continue
        name = normalize(subject.name)
        aliases = [normalize(a) for a in subject.aliases]
        if any(a == q for a in aliases):
            bucket = 0
        elif q in name or any(a.startswith(q) for a in aliases):
            bucket = 1
        else:
            continue
        scored.append(
            (
                bucket,
                _CATEGORY_ORDER.get(subject.category, 9),
                0 if name.startswith(q) else 1,
                len(subject.name),
                subject.name,
                subject,
            )
        )
    scored.sort(key=lambda item: item[:5])
    return [item[5] for item in scored[:limit]]


# 학기별로 흔히 편성되는 과목 예시. 학교마다 다르므로 "예시"일 뿐이다.
_COMMON_BY_PERIOD: dict[str, dict[str, list[str]]] = {
    CURRICULUM_2022: {
        "1-1": [
            "공통국어1", "공통수학1", "공통영어1", "통합사회1", "통합과학1", "과학탐구실험1",
            "한국사1",
        ],
        "1-2": [
            "공통국어2", "공통수학2", "공통영어2", "통합사회2", "통합과학2", "과학탐구실험2",
            "한국사2",
        ],
        "2-1": ["문학", "대수", "영어Ⅰ", "물리학", "화학", "생명과학", "지구과학", "정보"],
        "2-2": [
            "독서와 작문", "미적분Ⅰ", "확률과 통계", "영어Ⅱ", "사회와 문화", "역학과 에너지",
            "물질과 에너지", "세포와 물질대사",
        ],
        "3-1": [
            "화법과 언어", "기하", "미적분Ⅱ", "영어 독해와 작문", "전자기와 양자",
            "화학 반응의 세계", "생물의 유전", "데이터 과학",
        ],
        "3-2": [
            "주제 탐구 독서", "인공지능 수학", "심화 영어", "융합과학 탐구", "사회문제 탐구",
            "인공지능 기초", "수학과제 탐구",
        ],
    },
    CURRICULUM_2015: {
        "1-1": ["국어", "수학", "영어", "통합사회", "통합과학", "과학탐구실험", "한국사"],
        "1-2": ["국어", "수학", "영어", "통합사회", "통합과학", "과학탐구실험", "한국사"],
        "2-1": [
            "문학", "수학Ⅰ", "영어Ⅰ", "물리학Ⅰ", "화학Ⅰ", "생명과학Ⅰ", "지구과학Ⅰ", "사회·문화",
        ],
        "2-2": [
            "독서", "수학Ⅱ", "영어Ⅱ", "확률과 통계", "물리학Ⅰ", "화학Ⅰ", "생명과학Ⅰ", "지구과학Ⅰ",
        ],
        "3-1": [
            "언어와 매체", "화법과 작문", "미적분", "기하", "영어 독해와 작문", "물리학Ⅱ", "화학Ⅱ",
            "생명과학Ⅱ",
        ],
        "3-2": ["미적분", "확률과 통계", "인공지능 수학", "영어 독해와 작문", "정보"],
    },
}


def common_for_period(curriculum: str, grade: int, semester: int) -> list[Subject]:
    names = _COMMON_BY_PERIOD.get(curriculum, {}).get(f"{grade}-{semester}", [])
    return [s for name in names if (s := get_subject(f"{curriculum}:{name}")) is not None]
