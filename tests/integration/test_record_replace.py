"""설정 탭의 생기부 올리기·교체(mode=replace) — 대조 후 자동 반영하거나 멈춘다."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import app.services.record_review as record_review
import app.services.seteuk_service as seteuk_service
from app.core.exceptions import LLMUnavailableError
from app.models.academic_performance import AcademicPerformance
from app.models.activity import Activity, ActivityCategory, ActivityType
from app.models.user import User
from app.schemas.seteuk import AcademicPerformanceItem, ActivityItem, SeteukAnalysisResult
from tests.conftest import TestSessionLocal
from tests.integration.test_seteuk_upload import _set_profile_grade


@pytest.fixture(autouse=True)
def _patch_session_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seteuk_service, "AsyncSessionLocal", TestSessionLocal)


def _grade(grade: int, semester: int, subject: str, achievement: str = "A", **extra):
    return AcademicPerformanceItem(
        grade=grade, semester=semester, category="수학", subject=subject,
        achievement_grade=achievement, **extra,
    )


def _activity(grade: int, name: str, description: str = "탐구 보고서를 썼다.") -> ActivityItem:
    return ActivityItem(
        grade=grade,
        semester=None,
        activity_category=ActivityCategory.SUBJECT_SPECIALTY,
        subject="수학",
        activity_name=name,
        activity_type=ActivityType.REPORT,
        description=description,
    )


def _use_parse(monkeypatch: pytest.MonkeyPatch, result: SeteukAnalysisResult) -> None:
    async def _fake_parse(pdf_bytes: bytes) -> SeteukAnalysisResult:
        return result

    monkeypatch.setattr(seteuk_service, "parse_seteuk_pdf", _fake_parse)


async def _replace(client: AsyncClient, auth_headers: dict[str, str]) -> dict:
    created = await client.post(
        "/api/v1/seteuk/uploads",
        headers=auth_headers,
        files={"file": ("record.pdf", b"%PDF-1.4 ...", "application/pdf")},
        data={"mode": "replace"},
    )
    assert created.status_code == 201, created.text
    upload_id = created.json()["upload_id"]
    status = await client.get(f"/api/v1/seteuk/uploads/{upload_id}", headers=auth_headers)
    return status.json()


async def _user_id() -> uuid.UUID:
    async with TestSessionLocal() as db:
        return (await db.scalars(select(User.id))).one()


async def test_clean_record_is_imported_without_review(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _set_profile_grade(client, auth_headers, grade=2, semester=1)
    _use_parse(
        monkeypatch,
        SeteukAnalysisResult(
            student_name="홍길동",
            academic_performance=[_grade(1, 1, "공통수학1"), _grade(1, 2, "공통수학2")],
            activities=[_activity(1, "수열 탐구")],
        ),
    )

    status = await _replace(client, auth_headers)

    assert status["status"] == "done"
    assert status["mode"] == "replace"
    assert status["imported_at"] is not None
    assert status["review"]["state"] == "clean_imported"
    assert status["review"]["imported"]["academic_performance"] == 2
    async with TestSessionLocal() as db:
        assert len((await db.scalars(select(AcademicPerformance))).all()) == 2
        assert len((await db.scalars(select(Activity))).all()) == 1


async def test_blank_registered_course_is_filled_with_the_record_grade(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _set_profile_grade(client, auth_headers, grade=2, semester=1)
    user_id = await _user_id()
    async with TestSessionLocal() as db:
        db.add(
            AcademicPerformance(
                user_id=user_id, grade=1, semester=2, category="수학",
                subject="공통수학2", subject_code="2022:공통수학2",
            )
        )
        await db.commit()
    _use_parse(
        monkeypatch,
        SeteukAnalysisResult(academic_performance=[_grade(1, 2, "공통수학2", "B", raw_score=82)]),
    )

    status = await _replace(client, auth_headers)

    assert status["review"]["state"] == "clean_imported"
    async with TestSessionLocal() as db:
        rows = (await db.scalars(select(AcademicPerformance))).all()
    assert len(rows) == 1  # 중복으로 새 행을 만들지 않고 빈칸을 채웠다
    assert rows[0].achievement_grade == "B"
    assert rows[0].raw_score == 82
    assert rows[0].subject_code == "2022:공통수학2"


async def test_same_grade_is_skipped_and_different_grade_stops_for_review(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _set_profile_grade(client, auth_headers, grade=2, semester=1)
    user_id = await _user_id()
    async with TestSessionLocal() as db:
        db.add_all(
            [
                AcademicPerformance(
                    user_id=user_id, grade=1, semester=1, category="수학",
                    subject="공통수학1", achievement_grade="A",
                ),
                AcademicPerformance(
                    user_id=user_id, grade=1, semester=2, category="수학",
                    subject="공통수학2", achievement_grade="A",
                ),
            ]
        )
        await db.commit()
    _use_parse(
        monkeypatch,
        SeteukAnalysisResult(
            academic_performance=[_grade(1, 1, "공통수학1", "A"), _grade(1, 2, "공통수학2", "B")]
        ),
    )

    status = await _replace(client, auth_headers)

    review = status["review"]
    assert review["state"] == "needs_review"
    assert status["imported_at"] is None
    assert review["skipped_duplicates"] == {"academic_performance": 1}
    [conflict] = review["conflicts"]
    assert conflict["title"] == "공통수학2"
    assert conflict["differences"] == ["성취도: 학생 입력 A, 생기부 B"]
    async with TestSessionLocal() as db:
        assert len((await db.scalars(select(AcademicPerformance))).all()) == 2  # 아직 그대로


async def test_someone_elses_record_is_not_imported(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _set_profile_grade(client, auth_headers, grade=2, semester=1)
    _use_parse(
        monkeypatch,
        SeteukAnalysisResult(
            student_name="김철수",
            academic_performance=[_grade(1, 1, "공통수학1"), _grade(1, 2, "공통수학2")],
        ),
    )

    status = await _replace(client, auth_headers)

    assert status["review"]["state"] == "needs_review"
    assert [a["kind"] for a in status["review"]["anomalies"]] == ["name_mismatch"]
    async with TestSessionLocal() as db:
        assert (await db.scalars(select(AcademicPerformance))).all() == []


async def test_future_semester_is_an_anomaly_not_a_rejection(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _set_profile_grade(client, auth_headers, grade=1, semester=2)
    _use_parse(
        monkeypatch,
        SeteukAnalysisResult(
            academic_performance=[_grade(1, 1, "공통수학1"), _grade(2, 1, "대수")]
        ),
    )

    status = await _replace(client, auth_headers)

    assert status["status"] == "done"  # 온보딩과 달리 반려하지 않는다
    kinds = [a["kind"] for a in status["review"]["anomalies"]]
    assert "future_period" in kinds
    assert status["review"]["state"] == "needs_review"


async def test_a_record_missing_past_semesters_asks_for_confirmation(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _set_profile_grade(client, auth_headers, grade=2, semester=2)
    _use_parse(monkeypatch, SeteukAnalysisResult(academic_performance=[_grade(1, 1, "공통수학1")]))

    status = await _replace(client, auth_headers)

    assert [a["kind"] for a in status["review"]["anomalies"]] == ["stale_record"]


async def _add_manual_activity(name: str, description: str) -> None:
    user_id = await _user_id()
    async with TestSessionLocal() as db:
        db.add(
            Activity(
                user_id=user_id,
                grade=1,
                semester=2,
                activity_category="과목세부특기사항",
                subject="수학",
                activity_name=name,
                activity_type="report",
                description=description,
                keywords=[],
            )
        )
        await db.commit()


def _matches(monkeypatch: pytest.MonkeyPatch, matches: list[dict] | Exception) -> None:
    async def _fake(system_prompt, user_content, response_model):
        if isinstance(matches, Exception):
            raise matches
        return response_model.model_validate({"matches": matches})

    monkeypatch.setattr(record_review, "call_structured", _fake)


async def test_same_activity_is_not_imported_twice(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _set_profile_grade(client, auth_headers, grade=2, semester=1)
    await _add_manual_activity("수열 탐구", "등비수열로 인구를 모델링했다.")
    _use_parse(
        monkeypatch,
        SeteukAnalysisResult(activities=[_activity(1, "수열 탐구"), _activity(1, "확률 탐구")]),
    )
    # 존재하지 않는 번호(9)는 버려진다.
    _matches(
        monkeypatch,
        [
            {"existing_index": 0, "record_index": 0, "relation": "same"},
            {"existing_index": 0, "record_index": 9, "relation": "same"},
        ],
    )

    status = await _replace(client, auth_headers)

    assert status["review"]["state"] == "clean_imported"
    assert status["review"]["skipped_duplicates"] == {"activities": 1}
    async with TestSessionLocal() as db:
        names = sorted(a.activity_name for a in (await db.scalars(select(Activity))).all())
    assert names == ["수열 탐구", "확률 탐구"]


async def test_differing_activity_stops_for_review(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _set_profile_grade(client, auth_headers, grade=2, semester=1)
    await _add_manual_activity("설문 조사", "친구 30명에게 설문했다.")
    _use_parse(monkeypatch, SeteukAnalysisResult(activities=[_activity(1, "설문 조사 활동")]))
    _matches(
        monkeypatch,
        [
            {
                "existing_index": 0, "record_index": 0, "relation": "different",
                "difference": "학생 입력은 30명, 생기부는 50명",
            }
        ],
    )

    status = await _replace(client, auth_headers)

    [conflict] = status["review"]["conflicts"]
    assert conflict["section"] == "activities"
    assert conflict["differences"] == ["학생 입력은 30명, 생기부는 50명"]
    assert status["imported_at"] is None


async def test_activity_matching_failure_does_not_import_blindly(
    client: AsyncClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await _set_profile_grade(client, auth_headers, grade=2, semester=1)
    await _add_manual_activity("설문 조사", "친구 30명에게 설문했다.")
    _use_parse(monkeypatch, SeteukAnalysisResult(activities=[_activity(1, "설문 조사 활동")]))
    _matches(monkeypatch, LLMUnavailableError("down"))

    status = await _replace(client, auth_headers)

    assert [a["kind"] for a in status["review"]["anomalies"]] == ["activity_match_unavailable"]
    assert status["imported_at"] is None
