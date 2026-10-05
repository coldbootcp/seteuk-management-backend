"""생기부 확인 상담(kind=record_review) — 대조에서 멈춘 생기부를 학생과 확인하고 반영한다.

설정 탭에서 올린 생기부가 이상(이름·입학 연도 불일치, 아직 오지 않은 학기, 옛 문서)이나
충돌(직접 입력한 기록과 내용이 다름) 때문에 멈추면(`seteuk_uploads.review.state ==
"needs_review"`), 이 상담이 챗봇으로 학생에게 해명을 듣고 반영 방법을 정한다.

- 결정은 도구로만 저장된다(`record_decisions`): 반영 범위(scope)와 충돌별 선택(conflicts).
- 결정이 다 모이기 전에는 마무리 신호를 거부한다 — 프롬프트가 아니라 여기서 보증한다.
- 실제 반영은 학생이 버튼을 누를 때(`conclude`)만 일어난다.
- 로드맵은 바꾸지 않는다. 챗봇은 재설계를 추천만 할 수 있고, 그럴 도구가 없다.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConsultationNotReadyError
from app.models.academic_performance import AcademicPerformance
from app.models.activity import Activity
from app.models.consultation import ConsultationKind, ConsultationSession, ConsultationStatus
from app.models.conversation import Conversation, ConversationPurpose, TitleSource
from app.models.seteuk_upload import SeteukUpload, UploadMode, UploadStatus
from app.models.user import User
from app.schemas.seteuk import RecordReview, SeteukAnalysisResult

ConflictChoice = Literal["keep_mine", "use_record", "keep_both"]
_CHOICES = ("keep_mine", "use_record", "keep_both")


class RecordScope(BaseModel):
    """얼마나 반영할지. until이면 그 학기까지만(그 뒤 시점 기록은 뺀다)."""

    mode: Literal["all", "until", "none"]
    grade: int | None = None
    semester: int | None = None
    reason: str = ""


class RecordDecisions(BaseModel):
    scope: RecordScope | None = None
    conflicts: dict[str, ConflictChoice] = {}


# ── 세션 ────────────────────────────────────────────────────────────────


async def pending_upload(db: AsyncSession, user_id: uuid.UUID) -> SeteukUpload | None:
    """확인을 기다리는 교체 업로드(가장 최근 것 하나 — 업로드는 한 개만 남는다)."""
    upload = await db.scalar(
        select(SeteukUpload)
        .where(SeteukUpload.user_id == user_id)
        .order_by(SeteukUpload.created_at.desc())
        .limit(1)
    )
    if (
        upload is None
        or upload.mode != UploadMode.REPLACE.value
        or upload.status != UploadStatus.DONE.value
        or upload.imported_at is not None
        or not upload.review
        or upload.review.get("state") != "needs_review"
    ):
        return None
    return upload


async def get_or_create_session(db: AsyncSession, user: User) -> ConsultationSession:
    upload = await pending_upload(db, user.id)
    if upload is None:
        raise ConsultationNotReadyError("확인할 생기부가 없습니다")

    session = await db.scalar(
        select(ConsultationSession).where(
            ConsultationSession.user_id == user.id,
            ConsultationSession.kind == ConsultationKind.RECORD_REVIEW.value,
            ConsultationSession.source_upload_id == upload.id,
            ConsultationSession.status.in_(
                [ConsultationStatus.IN_PROGRESS.value, ConsultationStatus.READY.value]
            ),
        )
    )
    if session is not None:
        return session

    conversation = Conversation(
        user_id=user.id,
        purpose=ConversationPurpose.RECORD_REVIEW_CONSULTATION.value,
        title="생기부 확인",
        title_source=TitleSource.DEFAULT.value,
    )
    db.add(conversation)
    await db.flush()
    session = ConsultationSession(
        user_id=user.id,
        conversation_id=conversation.id,
        kind=ConsultationKind.RECORD_REVIEW.value,
        target_grade=user.current_grade or 1,
        target_semester=user.current_semester or 1,
        status=ConsultationStatus.IN_PROGRESS.value,
        source_upload_id=upload.id,
        record_decisions=RecordDecisions().model_dump(mode="json"),
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def _upload_of(db: AsyncSession, session: ConsultationSession) -> SeteukUpload | None:
    if session.source_upload_id is None:
        return None
    return await db.get(SeteukUpload, session.source_upload_id)


def _decisions(session: ConsultationSession) -> RecordDecisions:
    return RecordDecisions.model_validate(session.record_decisions or {})


def _review(upload: SeteukUpload | None) -> RecordReview | None:
    return RecordReview.model_validate(upload.review) if upload and upload.review else None


def outstanding(review: RecordReview, decisions: RecordDecisions) -> list[str]:
    """아직 정하지 않은 것. 비어 있어야 마무리할 수 있다."""
    missing: list[str] = []
    if review.anomalies and decisions.scope is None:
        missing.append("반영 범위(전부 / 특정 학기까지 / 반영 안 함)")
    if decisions.scope is not None and decisions.scope.mode == "none":
        return missing  # 반영하지 않기로 했으면 충돌은 정할 필요가 없다.
    for conflict in review.conflicts:
        if conflict.id not in decisions.conflicts:
            missing.append(f"충돌 {conflict.id}({conflict.title})")
    return missing


async def state(db: AsyncSession, session: ConsultationSession) -> dict[str, Any]:
    """화면(signal·세션 조회)과 프롬프트가 함께 쓰는 현재 상태."""
    upload = await _upload_of(db, session)
    review = _review(upload)
    decisions = _decisions(session)
    if upload is None or review is None:
        return {"available": False, "ready": False}
    return {
        "available": True,
        "ready": session.status == ConsultationStatus.READY.value,
        "concluded": session.status == ConsultationStatus.CONCLUDED.value,
        "file_name": upload.file_name,
        "anomalies": [a.model_dump(mode="json") for a in review.anomalies],
        "conflicts": [
            {**conflict.model_dump(mode="json"), "choice": decisions.conflicts.get(conflict.id)}
            for conflict in review.conflicts
        ],
        "scope": decisions.scope.model_dump(mode="json") if decisions.scope else None,
        "skipped_duplicates": review.skipped_duplicates,
        "outstanding": outstanding(review, decisions),
        # 확정 뒤: resolved(반영함)/discarded(반영 안 함)와 반영 건수
        "result_state": review.state,
        "imported": review.imported,
    }


# ── 도구 ────────────────────────────────────────────────────────────────


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


TOOL_SPECS: list[dict[str, Any]] = [
    _tool(
        "set_record_scope",
        "학생의 해명을 듣고 이 생기부를 얼마나 반영할지 저장한다. all=전부(현재 학기 이후는 원래"
        " 반영되지 않는다), until=grade·semester 학기까지만, none=반영하지 않음(다른 사람 것이거나"
        " 학생이 원하지 않을 때). 학생이 동의한 내용만 저장하라.",
        {
            "mode": {"type": "string", "enum": ["all", "until", "none"]},
            "grade": {"type": "integer", "minimum": 1, "maximum": 3},
            "semester": {"type": "integer", "minimum": 1, "maximum": 2},
            "reason": {"type": "string", "description": "학생이 설명한 이유 한 문장"},
        },
        ["mode", "reason"],
    ),
    _tool(
        "resolve_record_conflict",
        "직접 입력한 기록과 생기부가 다른 항목 하나를 학생이 어떻게 할지 저장한다."
        " keep_mine=학생 기록 유지(생기부 항목은 넣지 않음), use_record=생기부로 바꿈(학생"
        " 기록을 지우고 생기부 항목을 넣음), keep_both=둘 다 남김(서로 다른 활동일 때).",
        {
            "conflict_id": {"type": "string"},
            "choice": {"type": "string", "enum": list(_CHOICES)},
        },
        ["conflict_id", "choice"],
    ),
    _tool(
        "signal_ready_to_conclude",
        "정할 것을 모두 정하고 학생이 요약에 동의했을 때 부른다. 화면의 '확인한 내용으로 반영'"
        " 버튼이 켜진다. 정하지 않은 것이 남아 있으면 거부된다.",
        {},
        [],
    ),
]


async def execute_tool(
    db: AsyncSession, session: ConsultationSession, name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    upload = await _upload_of(db, session)
    review = _review(upload)
    if review is None:
        return {"error": "확인할 생기부가 더 이상 없습니다(다시 올렸거나 이미 반영됨)."}
    decisions = _decisions(session)

    if name == "set_record_scope":
        try:
            scope = RecordScope.model_validate(arguments)
        except ValidationError:
            return {"error": "mode는 all·until·none 중 하나여야 합니다."}
        if scope.mode == "until" and (scope.grade is None or scope.semester is None):
            return {"error": "until에는 grade와 semester가 모두 필요합니다."}
        decisions.scope = scope
    elif name == "resolve_record_conflict":
        conflict_id = str(arguments.get("conflict_id", ""))
        choice = arguments.get("choice")
        if conflict_id not in {c.id for c in review.conflicts}:
            return {"error": f"없는 충돌 id입니다: {conflict_id}"}
        if choice not in _CHOICES:
            return {"error": "choice는 keep_mine·use_record·keep_both 중 하나여야 합니다."}
        decisions.conflicts[conflict_id] = choice
    elif name == "signal_ready_to_conclude":
        missing = outstanding(review, decisions)
        if missing:
            return {"error": "아직 정하지 않은 것이 있습니다", "outstanding": missing}
        session.status = ConsultationStatus.READY.value
        session.ready_at = datetime.now(UTC)
        await db.commit()
        return {"ready": True}
    else:
        return {"error": f"알 수 없는 도구: {name}"}

    session.record_decisions = decisions.model_dump(mode="json")
    await db.commit()
    return {"stored": True, "outstanding": outstanding(review, decisions)}


# ── 반영 ────────────────────────────────────────────────────────────────


def _within(grade: int, semester: int | None, scope: RecordScope) -> bool:
    if scope.mode != "until":
        return True
    if grade != scope.grade:
        return grade < (scope.grade or 0)
    return semester is None or semester <= (scope.semester or 2)


async def conclude(db: AsyncSession, user: User, session: ConsultationSession) -> dict[str, Any]:
    """학생이 버튼을 눌렀을 때 정한 대로 반영한다. 로드맵은 건드리지 않는다."""
    from app.services import seteuk_service

    upload = await _upload_of(db, session)
    review = _review(upload)
    decisions = _decisions(session)
    if upload is None or review is None:
        raise ConsultationNotReadyError("확인할 생기부가 없습니다")
    if session.status != ConsultationStatus.READY.value or outstanding(review, decisions):
        raise ConsultationNotReadyError("아직 정하지 않은 것이 있습니다")

    scope = decisions.scope or RecordScope(mode="all")
    result: dict[str, Any]
    if scope.mode == "none":
        upload.review = {**upload.review, "state": "discarded"}
        result = {"state": "discarded"}
    else:
        raw = SeteukAnalysisResult.model_validate(upload.raw_result)
        filtered = seteuk_service._filter_future_grade_data(
            raw, user.current_grade, user.current_semester
        )
        plan = {name: list(indexes) for name, indexes in review.import_plan.items()}
        drop: dict[str, list[uuid.UUID]] = {"academic_performance": [], "activities": []}
        for conflict in review.conflicts:
            choice = decisions.conflicts.get(conflict.id)
            if choice in ("use_record", "keep_both"):
                plan.setdefault(conflict.section, []).append(conflict.parsed_index)
            if choice == "use_record":
                drop[conflict.section].append(conflict.existing_id)

        def period(section: str, index: int) -> tuple[int, int | None]:
            item = getattr(filtered, section)[index]
            return item.grade or 0, getattr(item, "semester", None)

        plan = {
            section: sorted(
                i
                for i in set(indexes)
                if 0 <= i < len(getattr(filtered, section))
                and _within(*period(section, i), scope)
            )
            for section, indexes in plan.items()
        }
        fill = {
            row_id: index
            for row_id, index in review.fill_placeholders.items()
            if 0 <= index < len(filtered.academic_performance)
            and _within(*period("academic_performance", index), scope)
        }

        # "생기부로 바꾸기"를 고른 학생 기록은 지운다(생기부 항목이 그 자리를 채운다).
        for model, section in (
            (AcademicPerformance, "academic_performance"),
            (Activity, "activities"),
        ):
            if drop[section]:
                await db.execute(
                    delete(model).where(
                        model.user_id == user.id,
                        model.source_upload_id.is_(None),
                        model.id.in_(drop[section]),
                    )
                )

        resolved = review.model_copy(update={"import_plan": plan, "fill_placeholders": fill})
        await db.commit()
        imported = await seteuk_service.apply_reviewed_import(db, user.id, upload, resolved)
        upload.review = {**upload.review, "state": "resolved", "imported": imported}
        result = {"state": "resolved", "imported": imported}

    session.status = ConsultationStatus.CONCLUDED.value
    session.concluded_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(session)
    return result


# ── 프롬프트 ────────────────────────────────────────────────────────────

PROMPT = """너는 '세특연구소'의 생기부 확인 담당이다. 학생이 올린 학교생활기록부(생기부)를 서버가
학생의 계정·기록과 대조했더니 확인이 필요한 점이 나왔다. <확인_상태>에 서버가 찾은 이상(anomalies)과
충돌(conflicts)이 있다. 네 일은 학생에게 정확히 해명을 듣고, 어떻게 반영할지 함께 정해 도구로
저장하는 것이다.

[원칙]
1. 존댓말(해요체)로, 학생을 "<이름> 학생"이라 부르거나 호칭 없이 말하라.
   학교생활기록부는 "학생부"가 아니라 "생기부"라고 부른다
   (학생부종합전형 같은 전형 이름은 그대로 쓴다).
2. 이상은 <확인_상태>.anomalies의 message를 근거로 구체적으로 짚어라. 없는 문제를 지어내지 마라.
   - name_mismatch: 본인 생기부가 맞는지 묻는다. 다른 사람 것이면 반영하지 않는다(none).
   - freshman_year_mismatch: 어느 쪽이 맞는지 묻는다. 생기부가 맞으면 반영하며 계정의 입학
     연도가 생기부 값으로 바뀐다고 알려라.
   - future_period: 현재 학기 설정이 낡았는지, 다른 문서인지 묻는다. 현재 학기가 바뀐 것이면
     "설정에서 현재 학년·학기를 고친 뒤 생기부를 다시 올려 달라"고 안내하고, 이번 것은 반영하지
     않거나(none) 지금 학기까지만(until) 반영한다.
   - stale_record: 더 최근 생기부가 있는지 묻는다. 있으면 그것을 다시 올리라고 안내하고(none),
     없으면 이 문서로 반영한다(all).
   - activity_match_unavailable: 직접 입력한 활동과 같은 활동이 두 번 들어갈 수 있다고 알리고
     그래도 반영할지 묻는다.
3. 이상이 하나라도 있으면 해명을 들은 뒤 set_record_scope로 반영 범위를 저장하라.
4. 충돌은 **한 번에 하나씩** 보여 주고(과목·학기, 학생 입력 vs 생기부, 다른 점), 학생이 고르면
   resolve_record_conflict로 저장한 뒤 다음으로 넘어가라. 생기부는 학교가 쓴 공식 기록이라는
   점은 알려 주되, 선택은 학생이 한다.
5. 로드맵(3개년 계획)은 이 상담에서 바꾸지 않는다. 반영될 기록 때문에 계획을 다시 세우는 게
   좋겠다고 판단되면 "학기 점검 상담에서 전체 재설계를 요청할 수 있다"고 **추천만** 하라.
6. 모두 정했으면 결과를 두세 줄로 요약해 확인받고, 학생이 동의하면 signal_ready_to_conclude를
   불러라. 그 턴에만 "화면의 '확인한 내용으로 반영' 버튼을 누르면 반영된다"고 한 번 안내하라.
7. 도구 오류·내부 이름(conflict id 등)은 학생에게 그대로 보이지 마라."""


def build_prompt(student: dict[str, Any], review_state: dict[str, Any]) -> str:
    return (
        f"{PROMPT}\n\n<학생>\n{json.dumps(student, ensure_ascii=False)}\n</학생>\n\n"
        f"<확인_상태>\n{json.dumps(review_state, ensure_ascii=False, default=str)}\n</확인_상태>"
    )


def student_facts(user: User) -> dict[str, Any]:
    return {
        "name": user.name,
        "current_grade": user.current_grade,
        "current_semester": user.current_semester,
        "freshman_academic_year": user.freshman_academic_year,
    }


def opening_instruction() -> str:
    return (
        "[시스템 안내: 학생이 방금 생기부를 올렸고 확인이 필요한 점이 있어 이 화면이 열렸습니다."
        " 학생은 아직 아무 말도 하지 않았습니다. 무엇 때문에 바로 반영하지 않았는지 두세 문장으로"
        " 알리고, 가장 중요한 이상(없으면 첫 번째 충돌) 하나에 대해서만 질문하세요. 도구는 호출하지"
        " 마세요.]"
    )
