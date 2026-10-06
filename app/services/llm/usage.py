"""AI 호출 토큰 사용량 기록.

프로바이더가 응답을 받을 때마다 부른다. 내용은 남기지 않고 숫자만 남긴다. 기록에 실패해도
AI 응답은 그대로 돌려준다 — 비용 통계 때문에 학생의 답변이 깨지면 안 된다.

Gemini(OpenAI 호환)는 "생각" 토큰을 별도 칸 없이 total_tokens에만 넣는다(예: 입력 3, 출력 9,
total 103). 생각 토큰도 출력 요금으로 과금되므로 total − 입력 − 출력으로 따로 계산한다.
"""

import logging
import uuid
from typing import Any

import structlog

from app.db.session import AsyncSessionLocal
from app.models.llm_usage_event import LLMUsageEvent

logger = logging.getLogger(__name__)


def usage_numbers(usage: Any) -> dict[str, int]:
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion = int(getattr(usage, "completion_tokens", 0) or 0)
    total = int(getattr(usage, "total_tokens", 0) or 0) or prompt + completion
    thinking = max(total - prompt - completion, 0)
    details = getattr(usage, "completion_tokens_details", None)
    reported = int(getattr(details, "reasoning_tokens", 0) or 0) if details else 0
    if reported and not thinking:
        # 생각 토큰을 출력 안에 따로 적어 주는 프로바이더(OpenAI 방식)는 출력에서 뺀다.
        thinking = reported
        completion = max(completion - reported, 0)
    prompt_details = getattr(usage, "prompt_tokens_details", None)
    cached = int(getattr(prompt_details, "cached_tokens", 0) or 0) if prompt_details else 0
    return {
        "input_tokens": prompt,
        "output_tokens": completion,
        "thinking_tokens": thinking,
        "cached_input_tokens": cached,
    }


async def record_usage(provider: str, model: str, kind: str, usage: Any) -> None:
    if usage is None:
        return
    try:
        numbers = usage_numbers(usage)
        context = structlog.contextvars.get_contextvars()
        raw_user = context.get("user_id")
        path = context.get("path")
        logger.info(
            "llm usage: provider=%s model=%s kind=%s path=%s %s",
            provider, model, kind, path, numbers,
        )
        async with AsyncSessionLocal() as db:
            db.add(
                LLMUsageEvent(
                    user_id=uuid.UUID(raw_user) if raw_user else None,
                    path=str(path)[:200] if path else None,
                    provider=provider,
                    model=model,
                    kind=kind,
                    **numbers,
                )
            )
            await db.commit()
    except Exception:
        logger.warning("failed to record llm usage", exc_info=True)
