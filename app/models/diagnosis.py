import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class DiagnosisStatus(StrEnum):
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class Diagnosis(Base):
    """진단은 생기부 입력만으로는 알 수 없는, 분석이 있어야 드러나는 내용을 저장하는
    단계다. 진단 보고서(API 응답)는 이 저장된 내용을 사용자가 보기 좋게 꺼내 주는
    것뿐이다. 각 필드는 서로 다른 섹션이고, 서로 독립적으로 계산된다 — LLM이 한 번에
    전부를 종합하려다 근거 없이 추상적으로 흐르는 것을 막기 위해서다."""

    __tablename__ = "diagnoses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DiagnosisStatus.PROCESSING.value
    )
    failure_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # 성적 추이 — LLM을 거치지 않는 순수 데이터(GradesTrend). 프론트가 그래프로 그린다.
    grades_trend: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 학기별 평가 — 학기당 1회 LLM 호출. 그 학기의 성적/독서/활동 데이터만 입력받아
    # 세 개의 독립된 텍스트(grades_review/reading_review/activities_review)를 낸다.
    semester_reviews: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # 진로 유기적 평가 — 활동 전체(계보 포함) + 수상 + 봉사를 함께 입력받아, 진로
    # 관점에서 의미 있는 것만 사슬로 엮는다(중요하지 않은 건 자동으로 빠진다).
    # 과거(completed)+미래(suggested)가 학년-학기 순으로 하나의 배열에 담긴다.
    career_thread: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # 활동 인벤토리 — 진로 유기적 평가와 달리 필터링하지 않고 전량을 역량 축
    # (전공관련교과역량/진로역량/공동체역량)으로 분류한다. 학년 단위로 배치 호출됨.
    activity_inventory: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # 지식 그래프 — 과목/키워드 겹침으로 추린 후보 쌍 중 LLM이 실제로 의미 있다고
    # 확정한 것만 담긴다(수직적 심화 / 수평적 융합).
    knowledge_graph_links: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # 종합 평가(SWOT) — semester_reviews/career_thread/activity_inventory의
    # "결과"만 입력받아 생성된다(원본 데이터 재조회 없음).
    strengths: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    weaknesses: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # 아직 기록에 없지만 남은 기간에 채우면 강점이 될 수 있는 것.
    opportunities: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # 외부 입시 환경(그런 데이터가 없다)이 아니라, 반복되거나 악화되는 내부
    # 패턴 — 방치하면 굳어질 위험 신호.
    threats: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # SWOT 중 가장 시급한 것 하나를 짚는 1~3문장.
    headline_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
