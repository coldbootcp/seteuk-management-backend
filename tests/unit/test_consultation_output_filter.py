from app.services.chat_service import filter_consultation_output_for_period


def test_filter_removes_past_semester_plans_for_second_year_student() -> None:
    result = filter_consultation_output_for_period(
        """**6개 학기 흐름**
- **1학년 1학기·1학년 2학기**: 반도체 기초 탐구를 시작합니다.
- **2학년 1학기**: 소자 원리를 탐구합니다.
- **2학년 2학기**: 집적회로 주제를 제안합니다.
- **3학년 1학기**: 심화 탐구를 이어갑니다.""",
        target_grade=2,
        target_semester=2,
    )

    assert "1학년" not in result
    assert "2학년 1학기" not in result
    assert "2학년 2학기" in result
    assert "3학년 1학기" in result


def test_filter_rephrases_six_semester_language_after_first_semester() -> None:
    result = filter_consultation_output_for_period(
        "앞으로 6개 학기의 탐구 여정을 설계합니다.",
        target_grade=2,
        target_semester=2,
    )

    assert "6개 학기" not in result
    assert "현재 학기부터 남은 학기" in result


def test_filter_does_not_claim_missing_activities_without_school_record() -> None:
    result = filter_consultation_output_for_period(
        "고1 2학기까지 반도체 공정·소자 물리 관련 심화 학습 활동이 전혀 기록되지 않았습니다.\n"
        "현재 학기에는 소자 물리 주제를 우선 검토해 보세요.",
        target_grade=2,
        target_semester=2,
        school_record_status="not_uploaded",
    )

    assert "전혀 기록되지" not in result
    assert "확인할 수 없습니다" in result
    assert "현재 학기" in result
