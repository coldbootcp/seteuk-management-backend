from app.services.chat import service_guide
from app.services.chat.prompts import build_system_prompt


def test_general_chatbot_knows_where_the_school_record_upload_is():
    prompt = build_system_prompt("{}", edit_mode=False)

    assert "{service_guide}" not in prompt
    assert "<서비스_안내>" in prompt
    assert "'생기부 연동' 버튼" in prompt
    # 안내서에 없는 기능은 지어내지 말라는 규칙이 함께 실린다.
    assert "지어내지 말고" in prompt


def test_every_sidebar_tab_is_in_the_guide_in_order():
    rendered = service_guide.render()
    names = [name for name, _ in service_guide.SIDEBAR_TABS]

    assert names == [
        "이번 학기", "3개년 흐름", "대시보드", "성적 관리", "시간표", "캘린더",
        "활동 & 세특", "수시 포트폴리오", "AI 컨설턴트", "프로필 설정",
    ]
    positions = [rendered.index(f"- {name}:") for name in names]
    assert positions == sorted(positions)


def test_edit_mode_prompt_also_carries_the_guide():
    assert "<서비스_안내>" in build_system_prompt("{}", edit_mode=True)
