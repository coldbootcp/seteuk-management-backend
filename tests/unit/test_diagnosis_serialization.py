import json
import uuid

from app.models.activity import Activity
from app.services.diagnosis.data import serialize_row


def test_serialized_rows_are_json_dumpable() -> None:
    """진단 프롬프트는 이 결과를 json.dumps로 감싸므로, 어떤 컬럼이 추가되더라도
    직렬화 가능해야 한다 — parent_activity_id(UUID)를 추가했을 때 실제로 깨졌다."""
    activity = Activity(
        user_id=uuid.uuid4(),
        parent_activity_id=uuid.uuid4(),
        grade=2,
        semester=1,
        activity_category="과목세부특기사항",
        activity_name="로지스틱 함수를 이용한 확산 곡선 보정",
        activity_type="report",
        description="…",
        keywords=["로지스틱 함수"],
    )

    serialized = serialize_row(activity)
    json.dumps(serialized, ensure_ascii=False)

    assert isinstance(serialized["parent_activity_id"], str)
    # 사용자 식별자와 내부 id는 프롬프트에 실리지 않는다.
    assert "user_id" not in serialized
    assert "id" not in serialized
