from app.services.chat_service import (
    _drop_dangling_fragment,
    _drop_repeated_exit_notice,
    filter_consultation_output_for_period,
)


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


def test_filter_rephrases_six_semester_without_counter() -> None:
    result = filter_consultation_output_for_period(
        "### 2. 제안하는 6학기 큰 흐름 (안)",
        target_grade=2,
        target_semester=2,
    )

    assert "6학기" not in result
    assert "현재 학기부터 남은 학기" in result


def test_filter_removes_repeated_direction_motivation_question() -> None:
    result = filter_consultation_output_for_period(
        "반도체공학 진로를 처음 정하게 된 계기나 특히 마음에 남는 경험이 있나요?\n"
        "이번 학기에는 소자 물리 주제를 우선 검토해 보세요.",
        target_grade=2,
        target_semester=2,
        has_declared_direction=True,
    )

    assert "계기" not in result
    assert "이번 학기" in result


def test_filter_removes_method_preference_question_but_keeps_topic_choice() -> None:
    result = filter_consultation_output_for_period(
        "이 중에서 끌리는 주제가 있나요? 아니면 시뮬레이션 도구를 활용한 탐구보다는 "
        "이론·개념 정리형 접근을 더 선호하시는 편인지 알려주시면, 그 방향에 맞춰 "
        "이번 학기 탐구 계획을 구체화해볼게요.",
        target_grade=2,
        target_semester=2,
    )

    assert "끌리는 주제" in result
    assert "시뮬레이션" not in result


def test_filter_does_not_assume_a_specific_current_course() -> None:
    result = filter_consultation_output_for_period(
        "물리Ⅱ 수업 내용과 연결해 탐구해 보세요.",
        target_grade=2,
        target_semester=2,
        has_current_course_data=False,
    )

    assert "물리Ⅱ" not in result
    assert "관련 교과" in result


def test_filter_hides_internal_draft_retry_and_preserves_draft_status() -> None:
    result = filter_consultation_output_for_period(
        "설계 저장 형식이 잘못되어 다시 시도하겠습니다. 계획이 잘 저장되었습니다. "
        "이 내용으로 확정해도 괜찮을까요?",
        target_grade=2,
        target_semester=2,
    )

    assert "형식이 잘못" not in result
    assert "계획 초안을 정리했습니다" in result
    assert "확정해도" in result


def test_filter_removes_premature_draft_confirmation_claim() -> None:
    result = filter_consultation_output_for_period(
        "계획 초안을 확정해 드리겠습니다. 계획 초안이 잘 정리되어 저장되었습니다. "
        "이 계획은 초안 상태이며, 나가기 버튼을 눌러야 실제로 확정됩니다.",
        target_grade=2,
        target_semester=2,
    )

    assert "확정해 드리겠습니다" not in result
    assert "저장되었습니다" not in result
    # 확정은 버튼으로 한다는 안내는 남되, 화면에 없는 '나가기'가 아니라 실제 버튼 이름으로.
    assert "나가기 버튼" not in result
    assert "'상담 마치고 메인 화면으로' 버튼" in result


def test_filter_does_not_claim_missing_activities_while_school_record_pending() -> None:
    """생기부 PDF는 있지만 처리가 아직 안 끝난 상태(processing/failed/
    awaiting_import)에서는 "아직 반영되지 않았다"는 안내문을 붙인다 — 실제로
    처리 중인 일이라 정확한 표현이다."""
    result = filter_consultation_output_for_period(
        "고1 2학기까지 반도체 공정·소자 물리 관련 심화 학습 활동이 전혀 기록되지 않았습니다.\n"
        "현재 학기에는 소자 물리 주제를 우선 검토해 보세요.",
        target_grade=2,
        target_semester=2,
        school_record_status="processing",
    )

    assert "전혀 기록되지" not in result
    assert "확인할 수 없습니다" in result
    assert "현재 학기" in result


def test_filter_does_not_repeat_reflection_notice_when_never_uploaded() -> None:
    """생기부를 애초에 올린 적 없는 학생(not_uploaded)에게는 "아직 반영되지
    않았다"는 문구를 매 턴 반복해서 붙이지 않는다 — 처리 중인 일이 아니므로
    부정확하고, 반복되면 불필요하게 거슬린다는 사용자 피드백에 따른 것이다.
    과대 단정 문장 자체는 여전히 지운다."""
    result = filter_consultation_output_for_period(
        "고1 2학기까지 반도체 공정·소자 물리 관련 심화 학습 활동이 전혀 기록되지 않았습니다.\n"
        "현재 학기에는 소자 물리 주제를 우선 검토해 보세요.",
        target_grade=2,
        target_semester=2,
        school_record_status="not_uploaded",
    )

    assert "전혀 기록되지" not in result
    assert "반영되지" not in result
    assert "현재 학기" in result


def test_filter_removes_an_invented_existing_plan_claim() -> None:
    result = filter_consultation_output_for_period(
        "2학년 2학기에 미세먼지 예측 모델링 활동이 제안되어 있습니다.\n"
        "이번 학기에는 관심 분야를 바탕으로 새 주제를 함께 검토해 볼 수 있어요.",
        target_grade=2,
        target_semester=2,
    )

    assert "미세먼지" not in result
    assert "새 주제" in result


def test_filter_keeps_a_claim_about_a_real_existing_plan_title() -> None:
    result = filter_consultation_output_for_period(
        "기존 계획의 반도체 소자 물리 탐구가 이번 학기에 제안되어 있습니다.",
        target_grade=2,
        target_semester=2,
        confirmed_plan_titles=["반도체 소자 물리 탐구"],
    )

    assert "반도체 소자 물리 탐구" in result


_REMINDER = (
    "이번 학기 목표를 정리했어요.\n"
    "그리고 다시 한 번 강조드리면, 이건 아직 초안이에요. 제가 확정하는 게 아니라 "
    "화면의 나가기 버튼을 눌러야 실제로 확정돼요.\n"
    "다음으로 주제를 골라 볼까요?"
)


def test_conclude_reminder_is_removed_outside_the_conclude_turn() -> None:
    result = filter_consultation_output_for_period(
        _REMINDER, target_grade=1, target_semester=1, allow_conclude_notice=False
    )

    assert "초안" not in result
    assert "확정" not in result
    assert "이번 학기 목표를 정리했어요." in result
    assert "다음으로 주제를 골라 볼까요?" in result


def test_conclude_reminder_stays_on_the_conclude_turn_with_the_real_button_name() -> None:
    result = filter_consultation_output_for_period(
        _REMINDER, target_grade=1, target_semester=1, allow_conclude_notice=True
    )

    assert "나가기" not in result
    assert "'상담 마치고 메인 화면으로' 버튼" in result


def test_flow_card_confirm_guidance_is_not_mistaken_for_the_conclude_reminder() -> None:
    text = "흐름이 마음에 드시면 카드의 '이 흐름으로 확정' 버튼을 눌러 주세요."
    result = filter_consultation_output_for_period(
        text, target_grade=1, target_semester=1, allow_conclude_notice=False
    )

    assert result == text


def test_registered_courses_are_kept_and_others_neutralized() -> None:
    text = "이번 학기 물리학Ⅰ 수업과 화학Ⅰ을 연결해요."
    result = filter_consultation_output_for_period(
        text,
        target_grade=2,
        target_semester=1,
        has_current_course_data=True,
        current_course_names=["물리학Ⅰ"],
    )

    assert "물리학Ⅰ" in result
    assert "화학Ⅰ" not in result


def test_filter_drops_indented_body_of_a_removed_past_semester_item() -> None:
    result = filter_consultation_output_for_period(
        """**[3개년 학술 로드맵 큰 그림]**

- **1학년 1학기 — 도체와 반도체의 차이 규명 (통합과학)**
  원자 구조 관점에서 전기가 통하는 조건을 묻는 단계예요.

- **2학년 1학기(지금) — 논리 게이트와 불 대수**
  트랜지스터로 게이트를 구성합니다.""",
        target_grade=2,
        target_semester=1,
    )

    assert "1학년" not in result
    assert "원자 구조" not in result
    assert "2학년 1학기(지금)" in result
    assert "트랜지스터로 게이트를 구성합니다." in result


def test_filter_keeps_future_semester_courses_and_collapses_placeholders() -> None:
    result = filter_consultation_output_for_period(
        """- **2학년 1학기 — 논리 게이트 (물리학Ⅰ·정보2)**
- **2학년 1학기 — 함수 해석 (수학Ⅰ·Ⅱ)**
- **2학년 2학기 — MOSFET 모델링 (물리학Ⅱ·미적분)**""",
        target_grade=2,
        target_semester=1,
        has_current_course_data=False,
    )

    assert "물리학Ⅰ" not in result
    assert "(관련 교과)" in result
    assert "관련 교과·관련 교과" not in result
    assert "물리학Ⅱ·미적분" in result
    assert "·Ⅱ" not in result.replace("물리학Ⅱ·미적분", "")


def test_dangling_fragment_before_a_tool_call_is_dropped() -> None:
    text = "네, 좋아요. 초안은 나가기 버튼을 눌러야 확정돼요.\n\n그럼"
    assert _drop_dangling_fragment(text) == "네, 좋아요. 초안은 나가기 버튼을 눌러야 확정돼요.\n"


def test_finished_sentence_before_a_tool_call_is_kept() -> None:
    text = "초안을 정리할게요."
    assert _drop_dangling_fragment(text) == text


def test_short_period_notation_is_read_as_a_semester() -> None:
    result = filter_consultation_output_for_period(
        """- 1-1: 전하·전류 기초 원리 (통합과학)
- **2-1(이번 학기): 도핑 효과 규명** (물리학Ⅰ)
- 2-2: pn 접합 다이오드 모델링 (물리학Ⅱ, 미적분)
- 주제는 1-2개만 골라도 괜찮아요.""",
        target_grade=2,
        target_semester=1,
        has_current_course_data=False,
    )

    assert "1-1" not in result
    assert "2-1(이번 학기): 도핑 효과 규명** (관련 교과)" in result
    assert "(물리학Ⅱ, 미적분)" in result
    assert "1-2개만" in result


def test_exit_notice_is_kept_once_per_turn() -> None:
    text = "요약입니다.\n실제 확정은 화면의 나가기 버튼을 눌러야 해요. 지금 누르시면 돼요."
    assert _drop_repeated_exit_notice(text, already_given=False) == text
    assert _drop_repeated_exit_notice(text, already_given=True) == "요약입니다."


def test_exit_notice_repeated_within_one_paragraph_is_kept_once() -> None:
    text = (
        "초안이에요. 나가기 버튼을 눌러야 저장돼요. 다음에 또 봐요. "
        "준비되면 나가기 버튼을 눌러주세요!"
    )
    assert _drop_repeated_exit_notice(text, already_given=False) == (
        "초안이에요. 나가기 버튼을 눌러야 저장돼요. 다음에 또 봐요."
    )


def test_a_current_line_that_cites_a_past_semester_as_its_source_is_kept() -> None:
    result = filter_consultation_output_for_period(
        """- **1학년 (개념 탐색)**: 반도체 기초 원리를 규명합니다.
- **2학년 (교과 융합)**: 1학년에서 다룬 에너지 밴드를 pn 접합 모델링으로 확장합니다.
1. **다이오드 I-V 특성 해석** — 1학년 통합과학에서 배운 전류 개념을 이어받습니다.""",
        target_grade=2,
        target_semester=1,
    )

    assert "개념 탐색" not in result
    assert "2학년 (교과 융합)" in result
    assert "다이오드 I-V 특성 해석" in result


def test_bracketed_period_and_doubled_subject_word() -> None:
    result = filter_consultation_output_for_period(
        """- **[2-2] MOS 모델링** (물리학Ⅱ·미적분)
2. **물리학Ⅰ 교과 개념을 소자 모델링에 적용**""",
        target_grade=2,
        target_semester=1,
        has_current_course_data=False,
    )

    assert "(물리학Ⅱ·미적분)" in result
    assert "관련 교과 개념을 소자 모델링에 적용" in result
    assert "관련 교과 교과" not in result
