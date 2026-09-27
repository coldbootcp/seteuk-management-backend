import pytest
from httpx import AsyncClient

import app.services.seteuk_service as seteuk_service
from app.schemas.seteuk import AttendanceItem, SeteukAnalysisResult
from tests.conftest import TestSessionLocal

PDF_BYTES = b"%PDF-1.4 fake pdf body"


@pytest.fixture(autouse=True)
def _patch_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_parse(pdf_bytes: bytes) -> SeteukAnalysisResult:
        return SeteukAnalysisResult(attendance=[AttendanceItem(grade=1, total_days=190)])

    monkeypatch.setattr(seteuk_service, "parse_seteuk_pdf", _fake_parse)
    monkeypatch.setattr(seteuk_service, "AsyncSessionLocal", TestSessionLocal)


async def _new_activity(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.post(
        "/api/v1/activities",
        json={
            "grade": 1,
            "semester": 1,
            "activity_category": "수행평가",
            "activity_name": "수행평가 안내문 분석",
            "activity_type": "report",
            "description": "안내문을 읽고 조건을 정리함",
        },
        headers=headers,
    )
    return response.json()["id"]


async def test_uploaded_school_record_is_kept_and_downloadable(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """P-1에서 "원본은 저장하지 않는다"를 뒤집었다. 학생이 자기가 올린 파일을 다시
    확인할 수 있어야 한다."""
    created = await client.post(
        "/api/v1/seteuk/uploads",
        headers=auth_headers,
        files={"file": ("내_생기부.pdf", PDF_BYTES, "application/pdf")},
    )
    upload_id = created.json()["upload_id"]

    downloaded = await client.get(
        f"/api/v1/seteuk/uploads/{upload_id}/file", headers=auth_headers
    )
    assert downloaded.status_code == 200
    assert downloaded.content == PDF_BYTES
    assert "attachment" in downloaded.headers["content-disposition"]


async def test_someone_elses_upload_is_not_downloadable(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await client.post(
        "/api/v1/seteuk/uploads",
        headers=auth_headers,
        files={"file": ("x.pdf", PDF_BYTES, "application/pdf")},
    )
    upload_id = created.json()["upload_id"]

    signup = await client.post(
        "/api/v1/auth/signup",
        json={"email": "other-file@example.com", "password": "s3cure-passw0rd"},
    )
    other = {"Authorization": f"Bearer {signup.json()['access_token']}"}

    response = await client.get(f"/api/v1/seteuk/uploads/{upload_id}/file", headers=other)
    assert response.status_code == 404


async def test_attachment_round_trip(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    activity_id = await _new_activity(client, auth_headers)

    created = await client.post(
        f"/api/v1/activities/{activity_id}/attachments",
        headers=auth_headers,
        files={"file": ("안내문.pdf", PDF_BYTES, "application/pdf")},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["file_name"] == "안내문.pdf"
    assert body["size_bytes"] == len(PDF_BYTES)
    # 본문은 목록·생성 응답에 실리지 않는다 — 수 MB가 매번 따라오면 안 된다.
    assert "content" not in body

    listed = await client.get(
        f"/api/v1/activities/{activity_id}/attachments", headers=auth_headers
    )
    assert [a["id"] for a in listed.json()] == [body["id"]]

    downloaded = await client.get(
        f"/api/v1/activities/attachments/{body['id']}/file", headers=auth_headers
    )
    assert downloaded.content == PDF_BYTES

    assert (
        await client.delete(
            f"/api/v1/activities/attachments/{body['id']}", headers=auth_headers
        )
    ).status_code == 204
    assert (
        await client.get(f"/api/v1/activities/{activity_id}/attachments", headers=auth_headers)
    ).json() == []


async def test_attachment_rejects_disallowed_file_types(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """화면(accept)뿐 아니라 서버도 형식을 막는다 — API를 직접 불러도 PDF·DOCX·PPTX가
    아니면 저장 전에 거부한다. 확장자·선언 MIME은 위조할 수 있어 매직바이트가 최종 근거다."""
    activity_id = await _new_activity(client, auth_headers)

    # HTML 파일: 확장자·매직바이트 모두 허용 형식이 아님.
    html = await client.post(
        f"/api/v1/activities/{activity_id}/attachments",
        headers=auth_headers,
        files={"file": ("evil.html", b"<script>alert(1)</script>", "text/html")},
    )
    assert html.status_code == 422
    assert html.json()["error_code"] == "UNSUPPORTED_FILE"

    # 확장자만 .pdf로 위장하고 내용은 HTML — 매직바이트 검사로 걸러진다.
    fake = await client.post(
        f"/api/v1/activities/{activity_id}/attachments",
        headers=auth_headers,
        files={"file": ("fake.pdf", b"<html></html>", "application/pdf")},
    )
    assert fake.status_code == 422

    # DOCX(OOXML=ZIP, PK 시그니처)는 허용된다.
    docx = await client.post(
        f"/api/v1/activities/{activity_id}/attachments",
        headers=auth_headers,
        files={
            "file": (
                "보고서.docx",
                b"PK\x03\x04docx body",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert docx.status_code == 201


async def test_attachment_cannot_be_bolted_onto_someone_elses_activity(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    activity_id = await _new_activity(client, auth_headers)
    signup = await client.post(
        "/api/v1/auth/signup",
        json={"email": "other-attach@example.com", "password": "s3cure-passw0rd"},
    )
    other = {"Authorization": f"Bearer {signup.json()['access_token']}"}

    response = await client.post(
        f"/api/v1/activities/{activity_id}/attachments",
        headers=other,
        files={"file": ("x.pdf", PDF_BYTES, "application/pdf")},
    )
    assert response.status_code == 404
