"""'수정' 모드에서 챗봇이 실제로 실행할 수 있는 도구들.

토글이 켜져 있다는 것 자체가 사용자의 동의이므로 별도 확인 단계 없이 바로 실행하되,
**삭제 도구는 일부러 넣지 않았다** — 대화 중 오해로 3년치 기록이 지워지는 사고를 막기
위해, 삭제는 탭 UI의 명시적 조작으로만 가능하다. 각 도구는 이미 검증된 서비스 함수를
호출할 뿐이고, 대상 행은 전부 user_id로 좁혀 남의 데이터에 닿을 수 없다.
"""

import asyncio
import datetime as dt
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.academic_performance import AcademicPerformance
from app.models.activity import Activity, ActivityCategory, ActivityType
from app.models.award import Award
from app.models.plan_item import PlanItemOrigin, PlanItemType
from app.models.reading_activity import ReadingActivity
from app.models.user import User
from app.models.volunteer_record import VolunteerRecord
from app.schemas.plan import PlanItemCompleteRequest, PlanItemCreate
from app.schemas.recommendation import FollowUpRequest
from app.services import (
    diagnosis_service,
    plan_service,
    recommendation_service,
    record_service,
    student_interest_service,
)

_ACTIVITY_CATEGORIES = [c.value for c in ActivityCategory]
_ACTIVITY_TYPES = [t.value for t in ActivityType]
_PLAN_ITEM_TYPES = [t.value for t in PlanItemType]


def _uuid(value: Any) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _date(value: Any) -> dt.date | None:
    """LLM이 준 ISO 날짜를 정규화한다. "날짜는 항상 ISO 8601로 정규화하고 원문은
    raw_date에 보존한다"는 원칙을 챗봇 경로에서도 지키기 위한 것 — 해석에 실패하면
    조용히 버린다(원문은 어차피 raw_date에 남는다)."""
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


async def _add_reading(db: AsyncSession, user: User, args: dict[str, Any]) -> dict[str, Any]:
    row = await record_service.create_record(
        db,
        ReadingActivity,
        user.id,
        {
            "grade": args.get("grade") or user.current_grade,
            "semester": args.get("semester") or user.current_semester,
            "subject": args.get("subject"),
            "title": args["title"],
            "author": args.get("author"),
        },
    )
    return {"reading_id": str(row.id), "title": row.title}


async def _add_activity(db: AsyncSession, user: User, args: dict[str, Any]) -> dict[str, Any]:
    row = await record_service.create_record(
        db,
        Activity,
        user.id,
        {
            "grade": args.get("grade") or user.current_grade,
            "semester": args.get("semester") or user.current_semester,
            "activity_category": args.get("activity_category") or ActivityCategory.ETC.value,
            "subject": args.get("subject"),
            "activity_name": args["activity_name"],
            "activity_type": args.get("activity_type") or ActivityType.OTHER.value,
            "role": args.get("role"),
            "description": args.get("description") or args["activity_name"],
            "keywords": args.get("keywords") or [],
            "parent_activity_id": _uuid(args.get("parent_activity_id")),
        },
    )
    return {"activity_id": str(row.id), "activity_name": row.activity_name}


async def _update_activity(db: AsyncSession, user: User, args: dict[str, Any]) -> dict[str, Any]:
    activity_id = _uuid(args.get("activity_id"))
    if activity_id is None:
        raise AppError("activity_id가 올바르지 않습니다")
    fields = {
        key: value
        for key, value in args.items()
        if key != "activity_id" and value is not None
    }
    if "parent_activity_id" in fields:
        fields["parent_activity_id"] = _uuid(fields["parent_activity_id"])
    row = await record_service.update_record(db, Activity, user.id, activity_id, fields)
    return {"activity_id": str(row.id), "activity_name": row.activity_name}


async def _add_award(db: AsyncSession, user: User, args: dict[str, Any]) -> dict[str, Any]:
    row = await record_service.create_record(
        db,
        Award,
        user.id,
        {
            "name": args["name"],
            "rank": args.get("rank"),
            "date": _date(args.get("date")),
            "raw_date": args.get("raw_date"),
        },
    )
    return {"award_id": str(row.id), "name": row.name}


async def _add_volunteer(db: AsyncSession, user: User, args: dict[str, Any]) -> dict[str, Any]:
    row = await record_service.create_record(
        db,
        VolunteerRecord,
        user.id,
        {
            "grade": args.get("grade") or user.current_grade,
            "date": _date(args.get("date")),
            "place": args.get("place"),
            "content": args.get("content"),
            "hours": args.get("hours"),
            "raw_date": args.get("raw_date"),
        },
    )
    return {"volunteer_id": str(row.id), "place": row.place}


async def _add_academic_performance(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    row = await record_service.create_record(
        db,
        AcademicPerformance,
        user.id,
        {
            "grade": args.get("grade") or user.current_grade,
            "semester": args.get("semester") or user.current_semester,
            "category": args.get("category") or args["subject"],
            "subject": args["subject"],
            "units": args.get("units"),
            "achievement_grade": args.get("achievement_grade"),
            "raw_score": args.get("raw_score"),
            "rank": args.get("rank"),
        },
    )
    return {"academic_performance_id": str(row.id), "subject": row.subject}


async def _add_plan(db: AsyncSession, user: User, args: dict[str, Any]) -> dict[str, Any]:
    plan = await plan_service.create_plan_item(
        db,
        user.id,
        PlanItemCreate(
            item_type=args.get("item_type") or PlanItemType.ACTIVITY.value,
            title=args["title"],
            description=args.get("description"),
            subject=args.get("subject"),
            target_grade=args.get("target_grade"),
            target_semester=args.get("target_semester"),
            keywords=args.get("keywords") or [],
            source_activity_id=_uuid(args.get("source_activity_id")),
        ),
        origin=PlanItemOrigin.CHATBOT,
    )
    return {"plan_id": str(plan.id), "title": plan.title}


async def _update_plan(db: AsyncSession, user: User, args: dict[str, Any]) -> dict[str, Any]:
    plan_id = _uuid(args.get("plan_id"))
    if plan_id is None:
        raise AppError("plan_id가 올바르지 않습니다")
    fields = {key: value for key, value in args.items() if key != "plan_id" and value is not None}
    plan = await plan_service.update_plan_item(db, user.id, plan_id, fields)
    return {"plan_id": str(plan.id), "status": plan.status}


async def _complete_plan(db: AsyncSession, user: User, args: dict[str, Any]) -> dict[str, Any]:
    plan_id = _uuid(args.get("plan_id"))
    if plan_id is None:
        raise AppError("plan_id가 올바르지 않습니다")
    plan = await plan_service.complete_plan_item(db, user, plan_id, PlanItemCompleteRequest())
    return {
        "plan_id": str(plan.id),
        "created_activity_id": str(plan.completed_activity_id)
        if plan.completed_activity_id
        else None,
        "created_reading_id": str(plan.completed_reading_id)
        if plan.completed_reading_id
        else None,
    }


async def _remember(db: AsyncSession, user: User, args: dict[str, Any]) -> dict[str, Any]:
    entry = await student_interest_service.upsert_interest(
        db, user.id, args["field_key"], args["value"]
    )
    await db.commit()
    return {"field_key": entry.field_key, "value": entry.value}


async def _update_basics(db: AsyncSession, user: User, args: dict[str, Any]) -> dict[str, Any]:
    for field in ("name", "current_grade", "current_semester"):
        if args.get(field) is not None:
            setattr(user, field, args[field])
    await db.commit()
    return {
        "name": user.name,
        "current_grade": user.current_grade,
        "current_semester": user.current_semester,
    }


# create_task로 띄운 job이 가비지 컬렉션되지 않도록 참조를 붙들어 둔다.
_BACKGROUND_JOBS: set[asyncio.Task] = set()


async def _run_diagnosis(db: AsyncSession, user: User, args: dict[str, Any]) -> dict[str, Any]:
    """진단은 3단계 파이프라인이라 오래 걸린다 — 대화를 막지 않도록 job으로 띄우고
    id만 돌려준다. run_diagnosis_job은 자체 세션을 열므로 이 대화의 세션과 무관하다."""
    diagnosis = await diagnosis_service.create_diagnosis(db, user.id)
    task = asyncio.create_task(diagnosis_service.run_diagnosis_job(diagnosis.id, user.id))
    _BACKGROUND_JOBS.add(task)
    task.add_done_callback(_BACKGROUND_JOBS.discard)
    return {"diagnosis_id": str(diagnosis.id), "status": diagnosis.status}


async def _recommend_follow_up(
    db: AsyncSession, user: User, args: dict[str, Any]
) -> dict[str, Any]:
    activity_id = _uuid(args.get("source_activity_id"))
    if activity_id is None:
        raise AppError("source_activity_id가 올바르지 않습니다")
    recommendation = await recommendation_service.create_follow_up(
        db, user, FollowUpRequest(source_activity_id=activity_id)
    )
    return {
        "recommendation_id": str(recommendation.id),
        "options": [option["topic"] for option in recommendation.options],
    }


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


_GRADE = {"type": "integer", "description": "학년(1~3). 생략하면 학생의 현재 학년"}
_SEMESTER = {"type": "integer", "description": "학기(1~2). 생략하면 학생의 현재 학기"}

TOOL_SPECS: list[dict[str, Any]] = [
    _tool(
        "add_reading",
        "학생이 읽은 책을 독서 탭에 추가한다.",
        {
            "title": {"type": "string"},
            "author": {"type": "string"},
            "subject": {"type": "string", "description": "관련 교과"},
            "grade": _GRADE,
            "semester": _SEMESTER,
        },
        ["title"],
    ),
    _tool(
        "add_activity",
        "학생이 수행한 활동(탐구/발표/실험/프로젝트/수행평가 등)을 활동 탭에 추가한다. "
        "이 활동이 기존 활동을 발전시킨 것이면 parent_activity_id를 반드시 채워라.",
        {
            "activity_name": {"type": "string"},
            "description": {"type": "string"},
            "activity_category": {"type": "string", "enum": _ACTIVITY_CATEGORIES},
            "activity_type": {"type": "string", "enum": _ACTIVITY_TYPES},
            "subject": {"type": "string"},
            "role": {"type": "string"},
            "keywords": {"type": "array", "items": {"type": "string"}},
            "parent_activity_id": {
                "type": "string",
                "description": "이 활동이 고도화한 이전 활동의 id",
            },
            "grade": _GRADE,
            "semester": _SEMESTER,
        },
        ["activity_name"],
    ),
    _tool(
        "update_activity",
        "이미 기록된 활동의 내용을 수정한다. 바꿀 필드만 넣어라.",
        {
            "activity_id": {"type": "string"},
            "activity_name": {"type": "string"},
            "description": {"type": "string"},
            "activity_type": {"type": "string", "enum": _ACTIVITY_TYPES},
            "subject": {"type": "string"},
            "role": {"type": "string"},
            "keywords": {"type": "array", "items": {"type": "string"}},
            "parent_activity_id": {"type": "string"},
        },
        ["activity_id"],
    ),
    _tool(
        "add_award",
        "수상 경력을 추가한다.",
        {
            "name": {"type": "string"},
            "rank": {"type": "string"},
            "date": {
                "type": "string",
                "description": "ISO 8601 날짜(YYYY-MM-DD). 학생이 정확한 날짜를 말한 경우에만",
            },
            "raw_date": {"type": "string", "description": "학생이 말한 날짜 표현 원문"},
        },
        ["name"],
    ),
    _tool(
        "add_volunteer_record",
        "봉사 활동 기록을 추가한다.",
        {
            "place": {"type": "string"},
            "content": {"type": "string"},
            "hours": {"type": "integer"},
            "date": {
                "type": "string",
                "description": "ISO 8601 날짜(YYYY-MM-DD). 학생이 정확한 날짜를 말한 경우에만",
            },
            "raw_date": {"type": "string", "description": "학생이 말한 날짜 표현 원문"},
            "grade": _GRADE,
        },
        [],
    ),
    _tool(
        "add_academic_performance",
        "교과 성적을 추가한다.",
        {
            "subject": {"type": "string"},
            "category": {"type": "string", "description": "교과 구분(예: 수학, 과학)"},
            "units": {"type": "integer"},
            "achievement_grade": {"type": "string"},
            "raw_score": {"type": "number"},
            "rank": {"type": "string"},
            "grade": _GRADE,
            "semester": _SEMESTER,
        },
        ["subject"],
    ),
    _tool(
        "add_plan",
        "앞으로 할 일을 계획으로 등록한다. 특정 과거 활동의 후속이면 "
        "source_activity_id를 채워 계보를 이어라.",
        {
            "title": {"type": "string"},
            "description": {"type": "string"},
            "item_type": {"type": "string", "enum": _PLAN_ITEM_TYPES},
            "subject": {"type": "string"},
            "keywords": {"type": "array", "items": {"type": "string"}},
            "source_activity_id": {"type": "string"},
            "target_grade": _GRADE,
            "target_semester": _SEMESTER,
        },
        ["title"],
    ),
    _tool(
        "update_plan",
        "계획의 내용이나 상태를 바꾼다(status: planned/in_progress/done/dropped).",
        {
            "plan_id": {"type": "string"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "status": {"type": "string",
                       "enum": ["planned", "in_progress", "done", "dropped"]},
            "target_grade": _GRADE,
            "target_semester": _SEMESTER,
        },
        ["plan_id"],
    ),
    _tool(
        "complete_plan",
        "계획을 완료 처리한다. 활동/수행평가 계획은 활동 기록으로, 독서 계획은 "
        "독서 기록으로 자동 승격된다.",
        {"plan_id": {"type": "string"}},
        ["plan_id"],
    ),
    _tool(
        "remember",
        "학생에 대해 오래 기억해야 할 사실을 개인화 메모리에 저장하거나 갱신한다. "
        "진로 희망, 목표 학과, 관심 키워드, 시간 제약처럼 앞으로의 판단에 영향을 주는 "
        "것만 저장하라. field_key는 짧은 영문 스네이크케이스.",
        {
            "field_key": {"type": "string"},
            "value": {
                "type": ["string", "array", "object"],
                "description": "문자열, 문자열 배열, 또는 객체",
            },
        },
        ["field_key", "value"],
    ),
    _tool(
        "update_profile_basics",
        "이름/현재 학년/현재 학기처럼 이력이 필요 없는 기본 정보를 갱신한다.",
        {
            "name": {"type": "string"},
            "current_grade": {"type": "integer"},
            "current_semester": {"type": "integer"},
        },
        [],
    ),
    _tool(
        "run_diagnosis",
        "진단을 새로 실행한다. 결과가 나오기까지 시간이 걸리므로, 호출 후에는 "
        "'진단을 시작했고 잠시 뒤 진단 탭에서 확인할 수 있다'고 안내하라.",
        {},
        [],
    ),
    _tool(
        "recommend_follow_up",
        "특정 활동의 후속 탐구 주제를 추천받는다.",
        {"source_activity_id": {"type": "string"}},
        ["source_activity_id"],
    ),
]

TOOL_HANDLERS = {
    "add_reading": _add_reading,
    "add_activity": _add_activity,
    "update_activity": _update_activity,
    "add_award": _add_award,
    "add_volunteer_record": _add_volunteer,
    "add_academic_performance": _add_academic_performance,
    "add_plan": _add_plan,
    "update_plan": _update_plan,
    "complete_plan": _complete_plan,
    "remember": _remember,
    "update_profile_basics": _update_basics,
    "run_diagnosis": _run_diagnosis,
    "recommend_follow_up": _recommend_follow_up,
}


async def execute_tool(
    db: AsyncSession, user: User, name: str, args: dict[str, Any]
) -> dict[str, Any]:
    """도구 실행 결과를 항상 dict로 돌려준다. 실패해도 예외를 올리지 않고 error를
    담아 보내, 챗봇이 사용자에게 무엇이 왜 안 됐는지 설명할 수 있게 한다."""
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return {"error": f"알 수 없는 도구입니다: {name}"}
    try:
        return await handler(db, user, args)
    except AppError as exc:
        return {"error": exc.message}
    except Exception as exc:
        await db.rollback()
        return {"error": f"{type(exc).__name__}: {exc}"}
