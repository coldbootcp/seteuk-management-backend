import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 비밀번호 계정만 검증이 필요하다 — 구글/카카오는 제공자가 이미 이메일 소유를
    # 확인했으므로 로그인 시 이 값과 무관하게 통과한다.
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    google_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    # 회원 탈퇴 요청 시각. 즉시 삭제하지 않고 유예 기간(30일) 뒤 배치로 완전
    # 삭제한다 — 나중에 결제 기능이 생기면 거래기록 보관 의무와 맞물릴 수 있어,
    # 지금부터 "요청 시점"을 남겨 두는 구조로 만들어 둔다. 이 값이 있으면
    # 로그인 자체는 되지만 앱 사용은 막고 탈퇴 취소만 허용한다.
    withdrawal_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Identity data, not an "opinion" that evolves — unlike student_interests, no history.
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Current factual status, not a subjective answer — kept separate from
    # student_interests. No auto-advance-by-calendar logic yet (deferred).
    current_grade: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 학적사항이 밝힌 "1학년이었던 학년도"(예: 2018). 날짜만 있고 학년이 없는
    # 기록에 학년-학기를 붙이는 기준점이라, 생기부를 반영할 때 저장해 두고 이후의
    # 다른 기록에도 쓴다. 바깥 시계로는 대신할 수 없다 — 생기부는 몇 해 전 문서일
    # 수 있어서 오늘 날짜로 거꾸로 세면 모든 기록이 학년 범위 밖으로 떨어진다.
    freshman_academic_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_semester: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kakao_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
