"""날짜만 있는 기록에 학년-학기를 붙이기 위한 기준점.

생기부에는 날짜만 적혀 있고 학년이 없는 기록이 여럿이다(수상이 대표적이고, 봉사도
학년만 있고 학기가 없다). 그 날짜를 학년-학기로 옮기려면 "이 학생이 몇 학년도에
1학년이었는가"라는 기준점 하나가 필요하다.

**바깥 시계(오늘 날짜)를 기준점으로 쓰면 안 된다.** 생기부는 몇 해 전 문서일 수
있어서, 올해에서 거꾸로 세면 모든 기록이 학년 범위 밖으로 떨어진다(실제로 2019~
2021년 문서를 2026년에 올렸을 때 수상 43건이 전부 미판정이 됐다). 기준점은 문서
안에서 찾고, 한 번 찾으면 사용자에 저장해 이후의 날짜만 있는 기록에도 쓴다.

기준점은 정수 하나로 충분하다 — 1학년이었던 학사연도를 알면 나머지 학년은 거기서
더하고 빼면 나온다.
"""

from collections import Counter
from datetime import date

# 학년도는 3월에 시작한다. 1~2월은 앞 학년도에 속한다.
_ACADEMIC_YEAR_START_MONTH = 3
# 1학기는 3~8월, 2학기는 9~2월. 수상·행사는 학기 말에 몰려 이 경계로 충분했다.
_FIRST_SEMESTER_MONTHS = range(3, 9)


def academic_year_of(value: date) -> int:
    """그 날짜가 속한 학년도. 2019년 1월은 2018 학년도다."""
    return value.year if value.month >= _ACADEMIC_YEAR_START_MONTH else value.year - 1


def semester_of(value: date) -> int:
    """그 날짜가 속한 학기. 학년도와 달리 날짜만으로 정해진다."""
    return 1 if value.month in _FIRST_SEMESTER_MONTHS else 2


def infer_freshman_year(evidence: list[tuple[date, int]]) -> int | None:
    """(날짜, 그때의 학년) 쌍들에서 1학년이었던 학년도를 추린다.

    쌍 하나면 답이 나오지만 여러 개를 모아 다수결로 정한다 — 파서가 참가대상을
    잘못 읽은 행 하나가 전체를 어긋나게 만들면 안 되기 때문이다. 증거가 없으면
    None을 돌려주고, 그때는 학년을 지어내지 않는다.
    """
    votes = Counter(academic_year_of(when) - (grade - 1) for when, grade in evidence)
    if not votes:
        return None
    return votes.most_common(1)[0][0]


def grade_for(value: date, freshman_year: int | None) -> int | None:
    """날짜를 학년으로 옮긴다. 기준점이 없거나 3년 밖이면 판정하지 않는다."""
    if freshman_year is None:
        return None
    grade = academic_year_of(value) - freshman_year + 1
    return grade if 1 <= grade <= 3 else None


def period_for(value: date, freshman_year: int | None) -> tuple[int, int] | None:
    """날짜 하나를 (학년, 학기)로. 학년을 정할 수 없으면 None."""
    grade = grade_for(value, freshman_year)
    return None if grade is None else (grade, semester_of(value))
