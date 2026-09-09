from app.services.review import review_options


def _option(topic: str, **kw) -> dict:
    return {"topic": topic, "connection_reason": "앞선 활동의 한계에서 출발했다.", **kw}


def test_clean_distinct_options_all_pass() -> None:
    reviews = review_options(
        [
            _option("지수함수 모델의 실측 데이터 검증"),
            _option("대기행렬 이론으로 배차 간격 최적화"),
            _option("설문으로 이용자 체감 대기시간 조사"),
        ]
    )
    assert all(r.passed for r in reviews)


def test_options_that_are_the_same_topic_in_different_words_are_dropped() -> None:
    """세 후보가 표현만 다른 같은 주제면 학생에게는 선택지가 하나뿐인 셈이다."""
    reviews = review_options(
        [
            _option("지수함수 모델의 실측 데이터 검증"),
            _option("실측 데이터로 지수함수 모델 검증하기"),
        ]
    )
    assert reviews[0].passed
    assert not reviews[1].passed
    assert "같은 주제" in reviews[1].flags[0]


def test_an_option_that_repeats_an_existing_plan_is_dropped() -> None:
    """이미 세운 계획을 다시 제안하면 새 제안이 아니다 — 챗봇이 같은 계획을 두 번
    만든 사고와 같은 부류다."""
    reviews = review_options(
        [_option("유체역학 기초서 독파 및 수학적 요약")],
        existing_plan_titles=["유체역학 기초서 독파 및 수학적 요약"],
    )
    assert not reviews[0].passed
    assert "이미 있는 계획" in reviews[0].flags[0]


def test_unsafe_certainty_about_admissions_is_dropped() -> None:
    """이 서비스는 입시 결과를 단정할 수 있는 위치가 아니다."""
    reviews = review_options(
        [_option("심화 탐구", record_potential="이 활동이면 서울대에 합격할 수 있습니다.")]
    )
    assert not reviews[0].passed
    assert "안전하지 않은 단정" in reviews[0].flags[0]


def test_medical_and_grade_guarantees_are_dropped() -> None:
    assert not review_options(
        [_option("건강 탐구", expected_output="이 방법으로 아토피를 완치할 수 있다.")]
    )[0].passed
    assert not review_options(
        [_option("성적 관리", career_relevance="이렇게 하면 1등급을 보장한다.")]
    )[0].passed


def test_an_empty_topic_never_reaches_the_student() -> None:
    assert not review_options([_option("   ")])[0].passed
