import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class ActivityCategory(StrEnum):
    """앞의 5개는 생기부 파서가 채우는 공식 항목이고, 뒤의 3개는 학생이 탭이나
    챗봇에서 직접 기록하는 항목이다 — 수행평가처럼 생기부에 별도 항목이 없지만
    세특의 재료가 되는 활동을 버리지 않기 위해 분리해 둔다."""

    SUBJECT_SPECIALTY = "과목세부특기사항"
    AUTONOMOUS = "자율활동"
    CLUB = "동아리활동"
    CAREER = "진로활동"
    BEHAVIOR = "행동특성및종합의견"
    ASSESSMENT = "수행평가"
    EXTERNAL = "교외활동"
    ETC = "기타"


SETEUK_SOURCED_CATEGORIES = frozenset(
    {
        ActivityCategory.SUBJECT_SPECIALTY,
        ActivityCategory.AUTONOMOUS,
        ActivityCategory.CLUB,
        ActivityCategory.CAREER,
        ActivityCategory.BEHAVIOR,
    }
)


class ActivityType(StrEnum):
    REPORT = "report"
    PRESENTATION = "presentation"
    EXPERIMENT = "experiment"
    PROJECT = "project"
    READING_LINKED = "reading_linked"
    OTHER = "other"


class Activity(Base):
    __tablename__ = "activities"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # Null means this row was entered some other way (e.g. manual edit in a future
    # tab-management API), not parsed from a 생기부 upload — re-uploading only
    # replaces rows that trace back to a previous upload, never these.
    source_upload_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("seteuk_uploads.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # 이 활동이 어떤 이전 활동을 고도화한 것인지 — 3년 계보 추적의 기록 쪽 절반.
    # plan_items를 거쳐 완료된 활동은 계획의 source_activity_id가 여기로 복사된다.
    # 실제로 언제 한 활동인지. 학생이 직접 입력할 때만 채워지고, 생기부에서
    # 파싱된 행은 비어 있다 — 생기부는 학년-학기까지만 알려 주기 때문이다.
    # 시점의 정본은 여전히 grade/semester다.
    performed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    # 활동 뒤 생각이 어떻게 달라졌는지 학생이 직접 쓴 글. description(무엇을 했는가)과
    # 분리해서 받는다 — 세특의 질을 가르는 건 사실 나열이 아니라 이 성찰 쪽이고,
    # 진단·검토가 둘을 구분해서 읽어야 "기록은 있는데 배운 게 안 보인다"고 말할 수 있다.
    reflection: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 이 활동이 실행한 로드맵 제안. 학생이 저장할 때 직접 고른 값이라, 정합 판정이
    # 글자 겹침으로 추측하는 대신 학생이 declare한 것을 그대로 쓸 수 있다.
    # use_alter: 이 FK가 activities → roadmap_plan_events → roadmap_nodes →
    # activities 순환을 닫는다. 이름을 주고 따로 걸어야 테이블 생성/삭제 순서를
    # 정렬할 수 있다(마이그레이션은 물론, 테스트의 create_all/drop_all도).
    source_plan_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "roadmap_plan_events.id",
            ondelete="SET NULL",
            name="fk_activities_source_plan_event_id",
            use_alter=True,
        ),
        nullable=True,
    )
    # 이 활동이 속한 주제(진로 사슬의 단위). parent_activity_id와 다른 축이다 —
    # 주제는 "어느 갈래인가", parent는 "그 갈래 안에서 무엇을 직접 이어받았는가".
    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("activity_threads.id", ondelete="SET NULL"), nullable=True
    )
    parent_activity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("activities.id", ondelete="SET NULL"), nullable=True
    )
    grade: Mapped[int] = mapped_column(Integer, nullable=False)
    semester: Mapped[int | None] = mapped_column(Integer, nullable=True)
    activity_category: Mapped[str] = mapped_column(String(50), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(100), nullable=True)
    activity_name: Mapped[str] = mapped_column(String(255), nullable=False)
    activity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    role: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str] = mapped_column(String, nullable=False)
    keywords: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    source_block: Mapped[str | None] = mapped_column(String, nullable=True)
    # Not computed by the parser yet — see docs/PARSER_SPEC.md; always null for now.
    parsing_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
