"""LLM 호출의 공용 진입점.

파서·진단·로드맵·추천·챗봇이 모두 여기를 지난다. 실제 모델 호출은
`provider.py`의 프로바이더가 맡고(P-3의 하네스 경계), 여기서는 **재시도와 검증**만
책임진다 — 재시도 정책은 호출부마다 달라야 하므로 프로바이더의 몫이 아니다.

- 파서는 블록 단위로 실패를 흡수한다(app/services/parser/llm.py).
- `call_structured`는 3회까지 재시도한 뒤 LLM_UNAVAILABLE로 올린다.
- `stream_chat`은 재시도하지 않는다 — 토큰을 일부 내보낸 뒤에는 되돌릴 수 없다.
"""

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel

from app.core.exceptions import LLMUnavailableError
from app.services.llm.provider import LLMProvider, get_provider

logger = logging.getLogger(__name__)

MAX_RETRIES = 3

__all__ = ["MAX_RETRIES", "LLMProvider", "call_structured", "get_provider", "stream_chat"]


async def call_structured[T: BaseModel](
    system_prompt: str, user_content: str, response_model: type[T]
) -> T:
    provider = get_provider()
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            raw = await provider.complete_json(system_prompt, user_content)
            return response_model.model_validate(json.loads(raw))
        except Exception as exc:
            last_error = exc
            logger.warning("LLM call failed (attempt %d/%d): %s", attempt, MAX_RETRIES, exc)

    raise LLMUnavailableError(f"LLM 응답 처리에 {MAX_RETRIES}회 실패했습니다: {last_error}")


async def stream_chat(
    messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
) -> AsyncIterator[Any]:
    async for chunk in get_provider().stream(messages, tools):
        yield chunk
