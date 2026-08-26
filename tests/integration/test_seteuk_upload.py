import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.services.seteuk_service as seteuk_service
from app.models.attendance import Attendance
from app.models.user import User
from app.schemas.seteuk import AttendanceItem, SeteukAnalysisResult
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


async def test_upload_persists_rows_automatically(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    # No separate confirm/apply step — a "done" status means the parsed rows are
    # already sitting in the domain tables (attendance here), not just in raw_result.
    create_response = await client.post(
        "/api/v1/seteuk/uploads",
        headers=auth_headers,
        files={"file": ("record.pdf", b"%PDF-1.4 ...", "application/pdf")},
    )
    upload_id = create_response.json()["upload_id"]

    status_response = await client.get(f"/api/v1/seteuk/uploads/{upload_id}", headers=auth_headers)
    assert status_response.json()["status"] == "done"

    async with TestSessionLocal() as db:
        rows = (await db.execute(select(Attendance))).scalars().all()

    assert len(rows) == 1
    assert rows[0].grade == 2
    assert rows[0].total_days == 190
    assert str(rows[0].source_upload_id) == upload_id


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

    second = await client.post(
        "/api/v1/seteuk/uploads",
        headers=auth_headers,
        files={"file": ("record.pdf", b"%PDF-1.4 ...", "application/pdf")},
    )
    second_upload_id = second.json()["upload_id"]

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

    await client.post(
        "/api/v1/seteuk/uploads",
        headers=auth_headers,
        files={"file": ("record.pdf", b"%PDF-1.4 ...", "application/pdf")},
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
