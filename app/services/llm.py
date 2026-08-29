"""DeepSeek 호출의 공용 진입점.

파서·진단·로드맵·추천·챗봇이 모두 같은 클라이언트를 쓴다. 재시도 정책은 호출부에
따라 다르다 — 파서는 블록 단위로 실패를 흡수하지만(app/services/parser/llm.py),
그 외에는 CLAUDE.md 일반 원칙대로 call_structured가 3회까지 재시도한 뒤
LLM_UNAVAILABLE로 올린다.
"""

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.exceptions import LLMUnavailableError

logger = logging.getLogger(__name__)
settings = get_settings()

MAX_RETRIES = 3


def build_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        max_retries=0,
    )


async def call_deepseek(client: AsyncOpenAI, system_prompt: str, user_content: str) -> str:
    response = await client.chat.completions.create(
        model=settings.deepseek_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content or ""


async def call_structured[T: BaseModel](
    system_prompt: str, user_content: str, response_model: type[T]
) -> T:
    client = build_client()
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            raw = await call_deepseek(client, system_prompt, user_content)
            return response_model.model_validate(json.loads(raw))
        except Exception as exc:
            last_error = exc
            logger.warning("LLM call failed (attempt %d/%d): %s", attempt, MAX_RETRIES, exc)

    raise LLMUnavailableError(f"LLM 응답 처리에 {MAX_RETRIES}회 실패했습니다: {last_error}")


async def stream_chat(
    messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
) -> AsyncIterator[Any]:
    """챗봇용 스트리밍 호출. 구조화 출력이 아니라 자연어 답변을 흘려보내야 하므로
    call_structured와 달리 재시도하지 않는다 — 토큰을 일부 내보낸 뒤에는 되돌릴 수
    없기 때문이다. 실패는 호출부가 SSE error 이벤트로 변환한다."""
    client = build_client()
    kwargs: dict[str, Any] = {
        "model": settings.deepseek_model,
        "messages": messages,
        "stream": True,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    stream = await client.chat.completions.create(**kwargs)
    async for chunk in stream:
        yield chunk
