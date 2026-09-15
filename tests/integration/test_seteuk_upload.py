import uuid
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.seteuk_service as seteuk_service
from app.models.academic_performance import AcademicPerformance
from app.models.activity import ActivityCategory, ActivityType
from app.models.attendance import Attendance
from app.models.award import Award
from app.models.seteuk_upload import SeteukUpload
from app.models.user import User
from app.schemas.seteuk import (
    AcademicPerformanceItem,
    ActivityItem,
    AttendanceItem,
    AwardItem,
    SeteukAnalysisResult,
    VolunteerRecordItem,
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


FAKE_RESULT_WITH_FUTURE_SEMESTER_DATA = SeteukAnalysisResult(
    academic_performance=[
        AcademicPerformanceItem(grade=2, semester=1, category="수학", subject="수학Ⅰ"),
        # 현재(2학년 1학기)와 같은 학년의 이후 학기 — 걸러져야 한다.
        AcademicPerformanceItem(grade=2, semester=2, category="수학", subject="수학Ⅱ"),
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
    ],
    awards=[
        # grade/semester가 없어(date만 있음) 이 검사의 대상이 아니다 — 그대로 남는다.
        AwardItem(name="전국 수학경시대회 금상"),
    ],
)


def _freshman_year_for_grade(grade: int) -> int:
    """오늘 날짜 기준으로 `grade`가 되도록 하는 입학 연도를 역산한다 —
    `_expected_grade_from_freshman_year`와 같은 3월 기준 규칙."""
    today = date.today()
    academic_year_now = today.year if today.month >= 3 else today.year - 1
    return academic_year_now - grade + 1


async def _set_profile_grade(
    client: AsyncClient, auth_headers: dict[str, str], grade: int, semester: int
) -> None:
    """검증 로직이 이제 입학 연도를 기준으로 삼으므로, 선언하는 학년과 앞뒤가
    맞는 입학 연도도 함께 채운다."""
    await client.post(
        "/api/v1/profile",
        json={
            "name": "홍길동",
            "grade": grade,
            "semester": semester,
            "freshman_academic_year": _freshman_year_for_grade(grade),
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


async def test_upload_drops_records_beyond_declared_current_semester(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """같은 학년 안에서도 아직 안 겪었어야 할 학기의 기록은 반영하지 않는다 —
    안 그러면 진단·로드맵이 "현재 위치"를 잘못 판단한다. (문서 최고 학년이
    선언한 학년을 넘지 않는 경우 — 넘는 경우는 아예 반려된다, 아래 별도 테스트.)"""
    await _set_profile_grade(client, auth_headers, grade=2, semester=1)

    async def _fake_parse(pdf_bytes: bytes) -> SeteukAnalysisResult:
        return FAKE_RESULT_WITH_FUTURE_SEMESTER_DATA

    monkeypatch.setattr(seteuk_service, "parse_seteuk_pdf", _fake_parse)

    created = await client.post(
        "/api/v1/seteuk/uploads",
        headers=auth_headers,
        files={"file": ("record.pdf", b"%PDF-1.4 ...", "application/pdf")},
    )
    upload_id = created.json()["upload_id"]
    status = (
        await client.get(f"/api/v1/seteuk/uploads/{upload_id}", headers=auth_headers)
    ).json()
    assert status["status"] == "done"
    await client.post(
        f"/api/v1/seteuk/uploads/{upload_id}/import", json={}, headers=auth_headers
    )

    result = (
        await client.get(f"/api/v1/seteuk/uploads/{upload_id}/result", headers=auth_headers)
    ).json()

    # 2-1과 2학년 학년단위 기록만 남고, 같은 학년의 2-2는 걸러진다.
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


async def test_upload_is_rejected_when_document_grade_exceeds_declared_grade(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """생기부에 선언한 현재 학년보다 높은 학년의 기록이 있으면(다른 사람 것이거나
    학년을 안 갱신한 채 최신 생기부를 올린 경우) 일부만 조용히 걸러내지 않고
    업로드 자체를 반려한다 — 학생이 무엇이 잘못됐는지 알고 바로잡게 한다."""
    await _set_profile_grade(client, auth_headers, grade=2, semester=1)

    async def _fake_parse(pdf_bytes: bytes) -> SeteukAnalysisResult:
        return SeteukAnalysisResult(
            academic_performance=[
                AcademicPerformanceItem(grade=2, semester=1, category="수학", subject="수학Ⅰ"),
                AcademicPerformanceItem(grade=3, semester=1, category="수학", subject="미적분"),
            ],
        )

    monkeypatch.setattr(seteuk_service, "parse_seteuk_pdf", _fake_parse)

    created = await client.post(
        "/api/v1/seteuk/uploads",
        headers=auth_headers,
        files={"file": ("record.pdf", b"%PDF-1.4 ...", "application/pdf")},
    )
    upload_id = created.json()["upload_id"]
    status = (
        await client.get(f"/api/v1/seteuk/uploads/{upload_id}", headers=auth_headers)
    ).json()

    assert status["status"] == "failed"
    assert "3학년" in status["failure_reason"]
    assert "2학년" in status["failure_reason"]

    # 반려된 업로드는 아무것도 반영되지 않는다.
    async with TestSessionLocal() as db:
        academic_rows = (await db.execute(select(AcademicPerformance))).scalars().all()
    assert academic_rows == []


async def test_upload_warns_but_accepts_when_document_grade_is_below_declared_grade(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """반대로 생기부가 선언한 현재 학년보다 낮은 학년까지만 있으면(최신 생기부를
    아직 안 올린 경우) 문서 자체는 앞뒤가 맞으므로 반영은 하되, 더 최근 생기부를
    올리라고 경고한다."""
    await _set_profile_grade(client, auth_headers, grade=3, semester=1)

    async def _fake_parse(pdf_bytes: bytes) -> SeteukAnalysisResult:
        return SeteukAnalysisResult(
            academic_performance=[
                AcademicPerformanceItem(grade=1, semester=1, category="수학", subject="수학"),
            ],
        )

    monkeypatch.setattr(seteuk_service, "parse_seteuk_pdf", _fake_parse)

    created = await client.post(
        "/api/v1/seteuk/uploads",
        headers=auth_headers,
        files={"file": ("record.pdf", b"%PDF-1.4 ...", "application/pdf")},
    )
    upload_id = created.json()["upload_id"]
    status = (
        await client.get(f"/api/v1/seteuk/uploads/{upload_id}", headers=auth_headers)
    ).json()
    assert status["status"] == "done"

    result = (
        await client.get(f"/api/v1/seteuk/uploads/{upload_id}/result", headers=auth_headers)
    ).json()

    # 문서가 선언한 학년보다 낮을 뿐 미래 시점은 아니므로 걸러지지 않는다.
    assert {item["subject"] for item in result["academic_performance"]} == {"수학"}

    warning = next(e for e in result["errors"] if e["block_id"] == "stale_school_record")
    assert "1학년" in warning["reason"]
    assert "3학년" in warning["reason"]


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


async def test_importing_one_category_does_not_wipe_another(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """검토 화면은 [상장]·[활동]처럼 카테고리별로 나눠 반영한다. 매번 전부 비우면
    상장을 반영하는 순간 앞서 반영한 성적이 사라진다 — 학생 눈에는 데이터 손실이다."""

    async def _fake_parse(pdf_bytes: bytes) -> SeteukAnalysisResult:
        return SeteukAnalysisResult(
            academic_performance=[
                AcademicPerformanceItem(grade=1, semester=1, category="수학", subject="수학"),
            ],
            awards=[AwardItem(name="교내 수학경시대회")],
        )

    monkeypatch.setattr(seteuk_service, "parse_seteuk_pdf", _fake_parse)
    created = await client.post(
        "/api/v1/seteuk/uploads",
        headers=auth_headers,
        files={"file": ("record.pdf", b"%PDF-1.4 ...", "application/pdf")},
    )
    upload_id = created.json()["upload_id"]

    # 성적을 먼저 반영하고,
    await client.post(
        f"/api/v1/seteuk/uploads/{upload_id}/import",
        json={"academic_performance": [0]},
        headers=auth_headers,
    )
    # 이어서 수상만 반영한다.
    await client.post(
        f"/api/v1/seteuk/uploads/{upload_id}/import",
        json={"awards": [0]},
        headers=auth_headers,
    )

    async with TestSessionLocal() as db:
        grades = (await db.execute(select(AcademicPerformance))).scalars().all()
        awards = (await db.execute(select(Award))).scalars().all()
    assert len(grades) == 1, "앞서 반영한 성적이 남아 있어야 한다"
    assert len(awards) == 1


async def test_importing_everything_still_replaces_everything(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """영역을 하나도 지정하지 않으면 전체 반영이고, 그때는 이전 반영분을 통째로
    대체한다 — 재업로드가 파서 데이터를 갈아치우는 기존 규칙 그대로다."""

    async def _fake_parse(pdf_bytes: bytes) -> SeteukAnalysisResult:
        return SeteukAnalysisResult(awards=[AwardItem(name="새 수상")])

    monkeypatch.setattr(seteuk_service, "parse_seteuk_pdf", _fake_parse)
    created = await client.post(
        "/api/v1/seteuk/uploads",
        headers=auth_headers,
        files={"file": ("record.pdf", b"%PDF-1.4 ...", "application/pdf")},
    )
    upload_id = created.json()["upload_id"]

    await client.post(
        f"/api/v1/seteuk/uploads/{upload_id}/import", json={}, headers=auth_headers
    )
    await client.post(
        f"/api/v1/seteuk/uploads/{upload_id}/import", json={}, headers=auth_headers
    )

    async with TestSessionLocal() as db:
        awards = (await db.execute(select(Award))).scalars().all()
    assert len(awards) == 1


async def test_latest_upload_lets_the_client_resume_without_remembering_the_id(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """파싱은 몇 분 걸린다. 그 사이 새로고침하면 클라이언트가 업로드 id를 잃는데,
    되찾을 경로가 없으면 진행 중인 업로드를 통째로 잃는다."""
    assert (await client.get("/api/v1/seteuk/uploads/latest", headers=auth_headers)).json() is None

    created = (
        await client.post(
            "/api/v1/seteuk/uploads",
            files={"file": ("record.pdf", b"%PDF-1.4", "application/pdf")},
            headers=auth_headers,
        )
    ).json()

    latest = (await client.get("/api/v1/seteuk/uploads/latest", headers=auth_headers)).json()
    assert latest["upload_id"] == created["upload_id"]
    assert latest["file_name"] == "record.pdf"
    # 아직 반영 전이라 imported_at이 비어 있다 — 화면은 이걸 보고 검토 단계를 되살린다.
    assert latest["imported_at"] is None

    await client.post(
        f"/api/v1/seteuk/uploads/{created['upload_id']}/import", json={}, headers=auth_headers
    )
    after = (await client.get("/api/v1/seteuk/uploads/latest", headers=auth_headers)).json()
    assert after["imported_at"] is not None


async def test_latest_is_not_mistaken_for_an_upload_id(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """"latest"가 {upload_id} 경로에 먼저 걸리면 UUID 파싱 오류가 난다."""
    response = await client.get("/api/v1/seteuk/uploads/latest", headers=auth_headers)
    assert response.status_code == 200


async def test_only_the_latest_upload_is_kept(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """생기부는 가장 최근 것 하나만 보관한다 — 원본 PDF와 지난 파싱 결과가 계정에
    쌓이지 않아야 한다."""
    first = (
        await client.post(
            "/api/v1/seteuk/uploads",
            files={"file": ("first.pdf", b"%PDF-1.4", "application/pdf")},
            headers=auth_headers,
        )
    ).json()
    await client.post(
        f"/api/v1/seteuk/uploads/{first['upload_id']}/import", json={}, headers=auth_headers
    )

    second = (
        await client.post(
            "/api/v1/seteuk/uploads",
            files={"file": ("second.pdf", b"%PDF-1.4", "application/pdf")},
            headers=auth_headers,
        )
    ).json()

    async with TestSessionLocal() as db:
        rows = list(await db.scalars(select(SeteukUpload)))
        assert [str(r.id) for r in rows] == [second["upload_id"]]

        # 지난 업로드에서 온 기록은 새 업로드로 옮겨 붙는다. 여기서 null이 되면 직접
        # 입력한 행과 구분되지 않아 다음 재업로드가 교체하지 못한다.
        attendance = list(await db.scalars(select(Attendance)))
        assert attendance
        assert all(str(a.source_upload_id) == second["upload_id"] for a in attendance)


async def test_replacing_an_upload_still_spares_manually_entered_rows(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """가장 최근 업로드만 남기더라도 재업로드 교체 규칙은 그대로여야 한다 —
    생기부에서 온 행은 교체되고 직접 입력한 행은 살아남는다."""
    manual = (
        await client.post(
            "/api/v1/attendance",
            json={"grade": 1, "total_days": 190, "absence": 0, "note": "직접 입력"},
            headers=auth_headers,
        )
    ).json()

    for name in ("first.pdf", "second.pdf"):
        created = (
            await client.post(
                "/api/v1/seteuk/uploads",
                files={"file": (name, b"%PDF-1.4", "application/pdf")},
                headers=auth_headers,
            )
        ).json()
        await client.post(
            f"/api/v1/seteuk/uploads/{created['upload_id']}/import", json={}, headers=auth_headers
        )

    listed = (await client.get("/api/v1/attendance?limit=100", headers=auth_headers)).json()
    ids = [row["id"] for row in listed["items"]]
    assert manual["id"] in ids
    # 두 번 올렸다고 생기부발 출결이 두 배가 되지 않는다.
    from_record = [row for row in listed["items"] if row["source_upload_id"]]
    assert len(from_record) == len(FAKE_RESULT.attendance)


async def test_the_student_can_fix_the_period_while_reviewing(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """세특은 과목당 한 덩어리로 쓰여 있어 어느 활동이 몇 학기인지 문서가 말해 주지
    않는다. 파서는 지어내지 않고 비워 두므로, 그 자리를 채울 수 있는 것은 검토
    화면에서의 학생 선택뿐이다."""
    created = (
        await client.post(
            "/api/v1/seteuk/uploads",
            files={"file": ("record.pdf", b"%PDF-1.4", "application/pdf")},
            headers=auth_headers,
        )
    ).json()

    await client.post(
        f"/api/v1/seteuk/uploads/{created['upload_id']}/import",
        json={
            "attendance": [0],
            "period_overrides": [{"section": "attendance", "index": 0, "grade": 3}],
        },
        headers=auth_headers,
    )

    listed = (await client.get("/api/v1/attendance?limit=10", headers=auth_headers)).json()
    assert [row["grade"] for row in listed["items"]] == [3]


async def test_an_override_out_of_range_is_ignored(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """화면이 낡은 파싱 결과를 들고 있을 수 있다. 없는 index를 가리켜도 반영 전체가
    실패하면 안 된다."""
    created = (
        await client.post(
            "/api/v1/seteuk/uploads",
            files={"file": ("record.pdf", b"%PDF-1.4", "application/pdf")},
            headers=auth_headers,
        )
    ).json()

    response = await client.post(
        f"/api/v1/seteuk/uploads/{created['upload_id']}/import",
        json={"period_overrides": [{"section": "activities", "index": 99, "semester": 2}]},
        headers=auth_headers,
    )
    assert response.status_code == 200


async def test_importing_one_section_leaves_the_others_alone(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """검토 화면은 카테고리를 하나씩 반영한다. 그때 지정하지 않은 영역은 손대지
    않아야 한다 — 앞서 반영한 것이 지워지면 마지막 카테고리만 남는다."""
    created = (
        await client.post(
            "/api/v1/seteuk/uploads",
            files={"file": ("record.pdf", b"%PDF-1.4", "application/pdf")},
            headers=auth_headers,
        )
    ).json()
    upload_id = created["upload_id"]

    await client.post(
        f"/api/v1/seteuk/uploads/{upload_id}/import",
        json={"attendance": [0]},
        headers=auth_headers,
    )
    assert (await client.get("/api/v1/attendance", headers=auth_headers)).json()["total"] == 1

    # 다른 영역만 지정해서 한 번 더 반영한다.
    await client.post(
        f"/api/v1/seteuk/uploads/{upload_id}/import",
        json={"academic_performance": []},
        headers=auth_headers,
    )

    still = (await client.get("/api/v1/attendance", headers=auth_headers)).json()
    assert still["total"] == 1, "지정하지 않은 영역이 지워졌습니다"


async def test_attendance_is_imported_even_though_the_review_screen_hides_it(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """출결은 검토 화면에 나오지 않는다 — 학생이 고를 대상이 아니라 챗봇이 참고하는
    자료다. 그래서 선택에 실려 오지 않는데, 지정되지 않은 영역이 반영에서 빠지는
    규칙 탓에 어느 경로로도 들어가지 못하고 있었다."""
    created = (
        await client.post(
            "/api/v1/seteuk/uploads",
            files={"file": ("record.pdf", b"%PDF-1.4", "application/pdf")},
            headers=auth_headers,
        )
    ).json()

    # 화면이 하는 것처럼 다른 영역만 지정해서 반영한다.
    await client.post(
        f"/api/v1/seteuk/uploads/{created['upload_id']}/import",
        json={"activities": []},
        headers=auth_headers,
    )

    listed = (await client.get("/api/v1/attendance", headers=auth_headers)).json()
    assert listed["total"] == len(FAKE_RESULT.attendance)


async def test_the_enrollment_year_survives_filtering_and_reaches_the_user(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """학적사항이 밝힌 입학 학년도는 날짜만 있는 기록에 학년을 붙이는 기준점이라
    사용자에 남아야 한다. 미래 학년 걸러내기가 결과를 다시 만들 때 이 값을
    떨어뜨린 적이 있다 — 기록만 덜어 내고 기준점은 가져가야 한다."""

    async def _fake_parse(pdf_bytes: bytes) -> SeteukAnalysisResult:
        return SeteukAnalysisResult(
            freshman_academic_year=2018,
            attendance=list(FAKE_RESULT.attendance),
        )

    monkeypatch.setattr(seteuk_service, "parse_seteuk_pdf", _fake_parse)
    await client.post(
        "/api/v1/profile",
        json={
            "name": "홍길동",
            "grade": 2,
            "semester": 1,
            "career_goal": {"goal": "해양 연구원"},
            "target_department": "해양학과",
            "interest_keywords": ["해양"],
            "career_specificity": {"level": "broad"},
        },
        headers=auth_headers,
    )
    created = (
        await client.post(
            "/api/v1/seteuk/uploads",
            files={"file": ("record.pdf", b"%PDF-1.4", "application/pdf")},
            headers=auth_headers,
        )
    ).json()
    await client.post(
        f"/api/v1/seteuk/uploads/{created['upload_id']}/import", json={}, headers=auth_headers
    )

    async with TestSessionLocal() as db:
        user = await db.scalar(select(User))
    assert user is not None and user.freshman_academic_year == 2018


# --- 입학 연도 기반 "지금쯤 몇 학년 몇 학기여야 하는지" 계산 — 순수 함수 단위 테스트 ---
# 실제 오늘 날짜에 의존하는 통합 테스트로는 학기 경계(3월/9월)를 안정적으로
# 검증할 수 없어서, today를 직접 주입해 계산 자체만 따로 검증한다.


def test_expected_period_within_first_semester() -> None:
    # 2025년 입학생은 2026년 5월(1학기 기간) 기준으로 2학년 1학기여야 한다.
    grade, semester = seteuk_service._expected_period_from_freshman_year(2025, date(2026, 5, 1))
    assert (grade, semester) == (2, 1)


def test_expected_period_within_second_semester() -> None:
    # 같은 입학생이 9월(2학기 기간)이면 2학년 2학기여야 한다.
    grade, semester = seteuk_service._expected_period_from_freshman_year(2025, date(2026, 9, 15))
    assert (grade, semester) == (2, 2)


def test_expected_period_before_march_is_still_previous_academic_year() -> None:
    # 1~2월은 새 학년도 시작 전이라 아직 이전 학년도(그리고 그 2학기)다.
    grade, semester = seteuk_service._expected_period_from_freshman_year(2025, date(2027, 2, 20))
    assert (grade, semester) == (2, 2)


def test_expected_period_caps_at_grade_three_for_graduates() -> None:
    # 입학한 지 3년이 넘으면(졸업) 학년은 3으로 묶는다 — 문서도 3학년을 못 넘는다.
    grade, _ = seteuk_service._expected_period_from_freshman_year(2018, date(2026, 9, 15))
    assert grade == 3


# --- 문서 내 최고 (학년, 학기) 탐지 — 순수 함수 단위 테스트 ---


def test_max_document_period_picks_highest_semester_at_highest_grade() -> None:
    result = SeteukAnalysisResult(
        academic_performance=[
            AcademicPerformanceItem(grade=1, semester=2, category="국어", subject="국어"),
            AcademicPerformanceItem(grade=2, semester=1, category="수학", subject="수학"),
            AcademicPerformanceItem(grade=2, semester=2, category="영어", subject="영어"),
        ],
    )
    assert seteuk_service._max_document_period(result) == (2, 2)


def test_max_document_period_is_none_semester_when_only_grade_level_records_exist() -> None:
    # 최고 학년에 학기 있는 기록이 하나도 없으면(자율활동 등만 있으면) 학기는
    # 알 수 없다는 뜻으로 None을 돌려준다.
    result = SeteukAnalysisResult(
        academic_performance=[
            AcademicPerformanceItem(grade=1, semester=1, category="국어", subject="국어"),
        ],
        volunteer_records=[VolunteerRecordItem(grade=2, hours=4, content="봉사")],
    )
    assert seteuk_service._max_document_period(result) == (2, None)


def test_max_document_period_is_none_when_no_grade_found_anywhere() -> None:
    assert seteuk_service._max_document_period(SeteukAnalysisResult()) is None
