"""LLM 호출 남용 방지 — 사용자별 24시간 슬라이딩 윈도우.

한도는 설정값이라 배포 환경마다 조절할 수 있고, 카운트는 DB에 있어 워커 수와
무관하게 일관된다.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import RateLimitedError
from app.models.usage_event import UsageAction, UsageEvent
from app.services.korean_text import with_particle

WINDOW = timedelta(hours=24)

_MESSAGES = {
    UsageAction.SETEUK_UPLOAD: "생기부 업로드",
    UsageAction.DIAGNOSIS: "진단",
    UsageAction.ROADMAP: "로드맵 생성",
    UsageAction.RECOMMENDATION: "후속 탐구 추천",
    UsageAction.CHAT_MESSAGE: "챗봇 대화",
}


def _limit_for(action: UsageAction) -> int:
    settings = get_settings()
    return {
        UsageAction.SETEUK_UPLOAD: settings.daily_upload_limit,
        UsageAction.DIAGNOSIS: settings.daily_diagnosis_limit,
        UsageAction.ROADMAP: settings.daily_roadmap_limit,
        UsageAction.RECOMMENDATION: settings.daily_recommendation_limit,
        UsageAction.CHAT_MESSAGE: settings.daily_chat_message_limit,
    }[action]


async def enforce_daily_limit(
    db: AsyncSession, user_id: uuid.UUID, action: UsageAction
) -> None:
    """한도를 넘지 않았으면 사용 1건을 기록한다. 실제 작업이 실패하면 그 1건은
    남지만, 남용 방지 목적에서는 과소 계상보다 과대 계상이 안전하다."""
    limit = _limit_for(action)
    since = datetime.now(UTC) - WINDOW

    used = await db.scalar(
        select(func.count())
        .select_from(UsageEvent)
        .where(
            UsageEvent.user_id == user_id,
            UsageEvent.action == action.value,
            UsageEvent.created_at >= since,
        )
    ) or 0

    if used >= limit:
        raise RateLimitedError(
            f"{with_particle(_MESSAGES[action], '은', '는')} 하루 {limit}회까지"
            " 가능합니다. 내일 다시 시도해주세요"
        )

    db.add(UsageEvent(user_id=user_id, action=action.value))
    await db.commit()
