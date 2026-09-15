from datetime import datetime

from pydantic import BaseModel


class AccountStatusResponse(BaseModel):
    email: str
    email_verified: bool
    has_password: bool
    google_linked: bool
    kakao_linked: bool
    withdrawal_requested_at: datetime | None
    # 프론트엔드가 D-day를 그대로 보여줄 수 있도록 서버에서 계산해 내려준다 —
    # 유예 일수(ACCOUNT_DELETION_GRACE_DAYS)는 설정값이라 클라이언트가 몰라도 된다.
    scheduled_deletion_at: datetime | None


class WithdrawAccountRequest(BaseModel):
    # 비밀번호 계정은 재확인을 요구한다 — 세션 탈취만으로 탈퇴가 되지 않게 하는
    # 최소한의 안전장치. 소셜 전용 계정은 비밀번호가 없으므로 생략한다.
    password: str | None = None
