from app.models.activity import Activity
from app.models.user import User
from app.services.diagnosis.data import get_semester_groups
from tests.conftest import TestSessionLocal


def _activity(user_id, *, grade: int, semester: int | None, name: str) -> Activity:
    return Activity(
        user_id=user_id,
        grade=grade,
        semester=semester,
        activity_category="창의적체험활동" if semester is None else "과목세부특기사항",
        activity_name=name,
        activity_type="other",
        description=f"{name} 내용",
    )


async def test_year_level_activities_reach_every_semester_of_that_grade() -> None:
    """생기부의 자율활동·진로활동은 학기를 나누지 않고 학년 단위로만 기록된다.
    이 행들을 학기 그룹에서 빼면 학기 리뷰가 기록의 상당 부분을 못 보고 "이 학기
    활동 기록이 없습니다"라고 단정한다 — 실제 데이터에서 157건 중 57건이었다."""
    async with TestSessionLocal() as db:
        user = User(email="semester-groups@example.com", password_hash="x")
        db.add(user)
        await db.commit()
        await db.refresh(user)

        db.add_all(
            [
                _activity(user.id, grade=2, semester=1, name="학기 활동"),
                _activity(user.id, grade=2, semester=None, name="자율활동"),
            ]
        )
        await db.commit()

        groups = {(g.grade, g.semester): g for g in await get_semester_groups(db, user.id)}

        # 학년 단위 활동만 있는 학기도 리뷰 대상이 된다.
        assert (2, 1) in groups and (2, 2) in groups
        assert [a.activity_name for a in groups[(2, 1)].activities] == ["학기 활동"]
        assert groups[(2, 2)].activities == []
        # 학기 활동과 섞지 않고 따로 담되, 그 학년의 두 학기 모두에서 근거로 보인다.
        for semester in (1, 2):
            assert [a.activity_name for a in groups[(2, semester)].year_activities] == ["자율활동"]
        assert "year_activities" in groups[(2, 2)].to_prompt_json()
