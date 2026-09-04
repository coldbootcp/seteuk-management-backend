import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.seteuk_service as seteuk_service
from app.models.academic_performance import AcademicPerformance
from app.models.activity import ActivityCategory, ActivityType
from app.models.attendance import Attendance
from app.models.user import User
from app.schemas.seteuk import (
    AcademicPerformanceItem,
    ActivityItem,
    AttendanceItem,
    AwardItem,
    SeteukAnalysisResult,
)
from tests.conftest import TestSessionLocal

FAKE_RESULT = SeteukAnalysisResult(
    attendance=[AttendanceItem(grade=2, total_days=190, absence=1, note="질병 결석 1일")],
)


@pytest.fixture(autouse=True)
def _patch_session_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    # run_parse_job opens its own session outside of FastAPI's dependency-injected
    # get_db, so it must be pointed at the same test database as everything else.
    monkeypatch.setattr(seteuk_service, "AsyncSessionLocal", TestSessionLocal)


@pytest.fixture(autouse=True)
def _patch_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_parse(pdf_bytes: bytes) -> SeteukAnalysisResult:
        return FAKE_RESULT

    monkeypatch.setattr(seteuk_service, "parse_seteuk_pdf", _fake_parse)


async def test_upload_rejects_non_pdf(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.post(
        "/api/v1/seteuk/uploads",
        headers=auth_headers,
        files={"file": ("record.txt", b"not a pdf", "text/plain")},
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == "UNSUPPORTED_FILE"


async def test_upload_requires_auth(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/seteuk/uploads", files={"file": ("record.pdf", b"%PDF-1.4 ...", "application/pdf")}
    )

    assert response.status_code == 401


async def test_upload_processes_and_returns_result(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    create_response = await client.post(
        "/api/v1/seteuk/uploads",
        headers=auth_headers,
        files={"file": ("record.pdf", b"%PDF-1.4 ...", "application/pdf")},
    )
    assert create_response.status_code == 201
    upload_id = create_response.json()["upload_id"]

    status_response = await client.get(f"/api/v1/seteuk/uploads/{upload_id}", headers=auth_headers)
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "done"
    assert status_response.json()["parsing_confidence"] is None

    result_response = await client.get(
        f"/api/v1/seteuk/uploads/{upload_id}/result", headers=auth_headers
    )
    assert result_response.status_code == 200
    body = result_response.json()
    assert body["attendance"] == [
        {"grade": 2, "total_days": 190, "absence": 1, "note": "질병 결석 1일"}
    ]


async def test_parsing_does_not_apply_until_the_student_imports(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """파싱과 반영은 다른 단계다. 파서가 잘못 읽은 항목을 그대로 밀어 넣지 않도록,
    학생이 검토 화면에서 고른 뒤에야 기록에 들어간다."""
    create_response = await client.post(
        "/api/v1/seteuk/uploads",
        headers=auth_headers,
        files={"file": ("record.pdf", b"%PDF-1.4 ...", "application/pdf")},
    )
    upload_id = create_response.json()["upload_id"]

    status_response = await client.get(f"/api/v1/seteuk/uploads/{upload_id}", headers=auth_headers)
    # done은 "읽어냈다"는 뜻이지 "반영했다"는 뜻이 아니다.
    assert status_response.json()["status"] == "done"
    assert status_response.json()["imported_at"] is None

    async with TestSessionLocal() as db:
        assert (await db.execute(select(Attendance))).scalars().all() == []

    imported = await client.post(
        f"/api/v1/seteuk/uploads/{upload_id}/import", json={}, headers=auth_headers
    )
    assert imported.status_code == 200
    assert imported.json()["imported"]["attendance"] == 1

    async with TestSessionLocal() as db:
        rows = (await db.execute(select(Attendance))).scalars().all()
    assert len(rows) == 1
    assert rows[0].grade == 2
    assert str(rows[0].source_upload_id) == upload_id

    status_response = await client.get(f"/api/v1/seteuk/uploads/{upload_id}", headers=auth_headers)
    assert status_response.json()["imported_at"] is not None


async def _get_test_user_id(db: AsyncSession) -> uuid.UUID:
    user = await db.scalar(select(User).where(User.email == "seteuk-tester@example.com"))
    assert user is not None
    return user.id


async def test_reupload_replaces_previous_upload_rows_only(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    first = await client.post(
        "/api/v1/seteuk/uploads",
        headers=auth_headers,
        files={"file": ("record.pdf", b"%PDF-1.4 ...", "application/pdf")},
    )
    first_upload_id = first.json()["upload_id"]
    await client.post(
        f"/api/v1/seteuk/uploads/{first_upload_id}/import", json={}, headers=auth_headers
    )

    second = await client.post(
        "/api/v1/seteuk/uploads",
        headers=auth_headers,
        files={"file": ("record.pdf", b"%PDF-1.4 ...", "application/pdf")},
    )
    second_upload_id = second.json()["upload_id"]
    await client.post(
        f"/api/v1/seteuk/uploads/{second_upload_id}/import", json={}, headers=auth_headers
    )

    async with TestSessionLocal() as db:
        rows = (await db.execute(select(Attendance))).scalars().all()

    assert len(rows) == 1
    assert str(rows[0].source_upload_id) == second_upload_id
    assert str(rows[0].source_upload_id) != first_upload_id


async def test_reupload_never_touches_manually_entered_rows(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    async with TestSessionLocal() as db:
        user_id = await _get_test_user_id(db)
        # source_upload_id=None simulates a row entered some other way (e.g. a future
        # manual tab-management edit), not parsed from any 생기부 upload.
        db.add(Attendance(user_id=user_id, grade=3, total_days=1, source_upload_id=None))
        await db.commit()

    created = await client.post(
        "/api/v1/seteuk/uploads",
        headers=auth_headers,
        files={"file": ("record.pdf", b"%PDF-1.4 ...", "application/pdf")},
    )
    await client.post(
        f"/api/v1/seteuk/uploads/{created.json()['upload_id']}/import",
        json={},
        headers=auth_headers,
    )

    async with TestSessionLocal() as db:
        rows = (await db.execute(select(Attendance))).scalars().all()

    grades = {row.grade for row in rows}
    assert 3 in grades  # the manually entered row survived
    assert 2 in grades  # the freshly parsed row is also there
    assert len(rows) == 2


async def test_other_user_cannot_access_upload(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    create_response = await client.post(
        "/api/v1/seteuk/uploads",
        headers=auth_headers,
        files={"file": ("record.pdf", b"%PDF-1.4 ...", "application/pdf")},
    )
    upload_id = create_response.json()["upload_id"]

    signup_response = await client.post(
        "/api/v1/auth/signup",
        json={"email": "other-user@example.com", "password": "s3cure-passw0rd"},
    )
    other_headers = {"Authorization": f"Bearer {signup_response.json()['access_token']}"}

    response = await client.get(f"/api/v1/seteuk/uploads/{upload_id}", headers=other_headers)

    assert response.status_code == 404
    assert response.json()["error_code"] == "UPLOAD_NOT_FOUND"


FAKE_RESULT_WITH_FUTURE_GRADE_DATA = SeteukAnalysisResult(
    academic_performance=[
        AcademicPerformanceItem(grade=2, semester=1, category="수학", subject="수학Ⅰ"),
        # 현재(2학년 1학기)와 같은 학년의 이후 학기 — 걸러져야 한다.
        AcademicPerformanceItem(grade=2, semester=2, category="수학", subject="수학Ⅱ"),
        # 현재보다 이후 학년 — 걸러져야 한다.
        AcademicPerformanceItem(grade=3, semester=1, category="수학", subject="미적분"),
    ],
    activities=[
        ActivityItem(
            grade=2,
            semester=1,
            activity_category=ActivityCategory.SUBJECT_SPECIALTY,
            activity_name="지수함수 모델링",
            activity_type=ActivityType.REPORT,
            description="지수함수로 확산을 모델링함.",
        ),
        # 같은 학년, 이후 학기 — 걸러져야 한다.
        ActivityItem(
            grade=2,
            semester=2,
            activity_category=ActivityCategory.SUBJECT_SPECIALTY,
            activity_name="로지스틱 함수 모델링",
            activity_type=ActivityType.REPORT,
            description="지수함수 모델을 로지스틱 함수로 보완함.",
        ),
        # 같은 학년, 학기 없는 학년 단위 기록(자율활동 등) — 허용된다.
        ActivityItem(
            grade=2,
            semester=None,
            activity_category=ActivityCategory.AUTONOMOUS,
            activity_name="학급자치회 활동",
            activity_type=ActivityType.OTHER,
            description="학급 행사를 기획함.",
        ),
        # 이후 학년 — 걸러져야 한다.
        ActivityItem(
            grade=3,
            semester=1,
            activity_category=ActivityCategory.SUBJECT_SPECIALTY,
            activity_name="미적분 심화 탐구",
            activity_type=ActivityType.REPORT,
            description="치환적분을 활용함.",
        ),
    ],
    awards=[
        # grade/semester가 없어(date만 있음) 이 검사의 대상이 아니다 — 그대로 남는다.
        AwardItem(name="전국 수학경시대회 금상"),
    ],
)


async def test_upload_drops_records_beyond_declared_current_grade(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """실제 문서에 학생이 아직 안 겪었어야 할 시점의 기록이 있으면(잘못된 파일,
    갱신 안 된 프로필 등) 반영하지 않는다 — 안 그러면 진단·로드맵이 "현재 위치"를
    잘못 판단한다."""
    await client.post(
        "/api/v1/profile",
        json={
            "name": "홍길동",
            "grade": 2,
            "semester": 1,
            "career_goal": {"goal": "연구원"},
            "target_department": "미정",
            "interest_keywords": [],
            "career_specificity": {"level": "broad"},
            "preferred_output_types": [],
            "activity_channels": [],
            "self_assessed_strengths": "",
            "self_assessed_weaknesses": "",
        },
        headers=auth_headers,
    )

    async def _fake_parse(pdf_bytes: bytes) -> SeteukAnalysisResult:
        return FAKE_RESULT_WITH_FUTURE_GRADE_DATA

    monkeypatch.setattr(seteuk_service, "parse_seteuk_pdf", _fake_parse)

    created = await client.post(
        "/api/v1/seteuk/uploads",
        headers=auth_headers,
        files={"file": ("record.pdf", b"%PDF-1.4 ...", "application/pdf")},
    )
    upload_id = created.json()["upload_id"]
    await client.get(f"/api/v1/seteuk/uploads/{upload_id}", headers=auth_headers)
    await client.post(
        f"/api/v1/seteuk/uploads/{upload_id}/import", json={}, headers=auth_headers
    )

    result = (
        await client.get(f"/api/v1/seteuk/uploads/{upload_id}/result", headers=auth_headers)
    ).json()

    # 2-1과 2학년 학년단위 기록만 남고, 같은 학년의 2-2와 3-1은 걸러진다.
    kept_subjects = {item["subject"] for item in result["academic_performance"]}
    assert kept_subjects == {"수학Ⅰ"}
    kept_activity_names = {item["activity_name"] for item in result["activities"]}
    assert kept_activity_names == {"지수함수 모델링", "학급자치회 활동"}
    # grade/semester가 없는 수상은 판단 근거가 없어 그대로 남는다.
    assert len(result["awards"]) == 1

    # 몇 건이 왜 빠졌는지 errors에 남는다.
    assert any(e["block_id"] == "future_grade_filter" for e in result["errors"])

    async with TestSessionLocal() as db:
        academic_rows = (await db.execute(select(AcademicPerformance))).scalars().all()
    assert {r.subject for r in academic_rows} == {"수학Ⅰ"}


FAKE_RESULT_FOR_SELECTION = SeteukAnalysisResult(
    academic_performance=[
        AcademicPerformanceItem(grade=1, semester=1, category="수학", subject="수학"),
        AcademicPerformanceItem(grade=1, semester=1, category="국어", subject="국어"),
        AcademicPerformanceItem(grade=1, semester=1, category="영어", subject="영어"),
    ],
    attendance=[AttendanceItem(grade=1, total_days=190, absence=0)],
)


async def test_student_can_import_only_the_rows_they_picked(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """파서가 잘못 읽은 항목이나 이제 와서 넣고 싶지 않은 것을 빼고 반영할 수 있어야
    한다 — 검토 단계를 둔 이유가 그것이다."""

    async def _fake_parse(pdf_bytes: bytes) -> SeteukAnalysisResult:
        return FAKE_RESULT_FOR_SELECTION

    monkeypatch.setattr(seteuk_service, "parse_seteuk_pdf", _fake_parse)

    created = await client.post(
        "/api/v1/seteuk/uploads",
        headers=auth_headers,
        files={"file": ("record.pdf", b"%PDF-1.4 ...", "application/pdf")},
    )
    upload_id = created.json()["upload_id"]

    imported = await client.post(
        f"/api/v1/seteuk/uploads/{upload_id}/import",
        # 성적은 0번과 2번만, 출결은 아예 안 넣는다.
        json={"academic_performance": [0, 2], "attendance": []},
        headers=auth_headers,
    )
    assert imported.json()["imported"] == {
        "attendance": 0,
        "academic_performance": 2,
        "reading_activities": 0,
        "awards": 0,
        "volunteer_records": 0,
        "activities": 0,
    }

    async with TestSessionLocal() as db:
        subjects = {r.subject for r in (await db.execute(select(AcademicPerformance))).scalars()}
        attendance = (await db.execute(select(Attendance))).scalars().all()
    assert subjects == {"수학", "영어"}
    assert attendance == []


async def test_importing_again_replaces_the_previous_import(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """검토 화면에서 선택을 바꿔 다시 반영할 수 있다. 그 업로드의 이전 반영분을
    대체하되, 직접 입력한 행은 건드리지 않는다."""

    async def _fake_parse(pdf_bytes: bytes) -> SeteukAnalysisResult:
        return FAKE_RESULT_FOR_SELECTION

    monkeypatch.setattr(seteuk_service, "parse_seteuk_pdf", _fake_parse)

    created = await client.post(
        "/api/v1/seteuk/uploads",
        headers=auth_headers,
        files={"file": ("record.pdf", b"%PDF-1.4 ...", "application/pdf")},
    )
    upload_id = created.json()["upload_id"]

    await client.post(
        f"/api/v1/seteuk/uploads/{upload_id}/import",
        json={"academic_performance": [0]},
        headers=auth_headers,
    )
    await client.post(
        f"/api/v1/seteuk/uploads/{upload_id}/import",
        json={"academic_performance": [1, 2]},
        headers=auth_headers,
    )

    async with TestSessionLocal() as db:
        subjects = {r.subject for r in (await db.execute(select(AcademicPerformance))).scalars()}
    assert subjects == {"국어", "영어"}


async def test_import_before_parsing_finishes_is_refused(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _never_finishes(pdf_bytes: bytes) -> SeteukAnalysisResult:
        raise RuntimeError("파싱 실패")

    monkeypatch.setattr(seteuk_service, "parse_seteuk_pdf", _never_finishes)
    created = await client.post(
        "/api/v1/seteuk/uploads",
        headers=auth_headers,
        files={"file": ("record.pdf", b"%PDF-1.4 ...", "application/pdf")},
    )

    response = await client.post(
        f"/api/v1/seteuk/uploads/{created.json()['upload_id']}/import",
        json={},
        headers=auth_headers,
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "UPLOAD_NOT_READY"
