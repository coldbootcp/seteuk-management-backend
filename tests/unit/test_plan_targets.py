import uuid

from app.models.user import User
from app.schemas.plan import RoadmapGenerateRequest
from app.services.activity_lineage_service import _root_of
from app.services.plan_service import _target_semesters


def _user(grade: int | None, semester: int | None) -> User:
    return User(email="x@example.com", current_grade=grade, current_semester=semester)


def test_roadmap_targets_start_after_the_current_semester() -> None:
    assert _target_semesters(_user(2, 1), RoadmapGenerateRequest()) == [(2, 2), (3, 1), (3, 2)]


def test_roadmap_targets_respect_the_requested_end() -> None:
    request = RoadmapGenerateRequest(until_grade=3, until_semester=1)
    assert _target_semesters(_user(1, 2), request) == [(2, 1), (2, 2), (3, 1)]


def test_roadmap_covers_all_three_years_when_grade_is_unknown() -> None:
    # 온보딩만 마치고 학년을 안 밝힌 사용자도 로드맵을 받을 수 있어야 한다.
    assert len(_target_semesters(_user(None, None), RoadmapGenerateRequest())) == 6


def test_last_semester_has_nothing_left_to_plan() -> None:
    assert _target_semesters(_user(3, 2), RoadmapGenerateRequest()) == [(3, 2)]


def test_lineage_root_walk_survives_a_cycle() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    # 데이터가 손상돼 부모 관계가 순환하더라도 무한 루프에 빠지면 안 된다.
    assert _root_of(a, {a: b, b: a}) in {a, b}


def test_lineage_root_ignores_a_dangling_parent() -> None:
    child, missing = uuid.uuid4(), uuid.uuid4()
    assert _root_of(child, {child: missing}) == child
