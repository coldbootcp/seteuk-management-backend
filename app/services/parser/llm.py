import asyncio
import json
import logging

from openai import (
    APIConnectionError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
    RateLimitError,
)

from app.schemas.seteuk import LLMActivityDraftList
from app.services.llm import get_provider

__all__ = ["get_provider", "parse_block"]

logger = logging.getLogger(__name__)

# 재시도해도 같은 답이 나올 실패와, 다시 부르면 될 실패를 나눈다. 앞의 것은
# 모델이 스키마에 맞지 않는 응답을 준 경우이고(PARSER_SPEC 2.5의 "재시도 없음"이
# 가리키는 것이 이쪽이다), 뒤의 것은 연결·혼잡 같은 일시적인 사정이다.
_TRANSIENT = (APITimeoutError, APIConnectionError, RateLimitError, InternalServerError)
_MAX_TRANSIENT_ATTEMPTS = 3


async def parse_block(
    client: AsyncOpenAI, system_prompt: str, block_id: str, block_text: str
) -> tuple[LLMActivityDraftList | None, str | None]:
    """블록 하나를 모델에 맡긴다. 실패는 블록 단위로 흡수하고 나머지 배치는 계속 간다.

    응답이 스키마에 맞지 않으면 재시도하지 않는다 — 같은 입력에 같은 답이 올
    가능성이 높고, 그건 프롬프트 문제다(docs/PARSER_SPEC.md 2.5).

    다만 타임아웃·연결 실패는 다르다. 실제 생기부 검증에서 이것 때문에 블록 4개가
    통째로 빠져 활동이 156건에서 97건으로 줄어든 적이 있다. 같은 입력을 다시
    보내면 대개 성공하므로, 이런 실패만 짧은 backoff로 다시 시도한다.
    """
    for attempt in range(1, _MAX_TRANSIENT_ATTEMPTS + 1):
        try:
            raw = await client.complete_json(system_prompt, block_text)
            return LLMActivityDraftList.model_validate(json.loads(raw)), None
        except _TRANSIENT as exc:
            if attempt == _MAX_TRANSIENT_ATTEMPTS:
                logger.warning(
                    "block parse failed after %d attempts: block_id=%s",
                    attempt,
                    block_id,
                    exc_info=True,
                )
                return None, f"{type(exc).__name__}: {exc}"
            logger.info(
                "block parse retrying (%d/%d): block_id=%s reason=%s",
                attempt,
                _MAX_TRANSIENT_ATTEMPTS,
                block_id,
                type(exc).__name__,
            )
            await asyncio.sleep(2 ** (attempt - 1))
        except Exception as exc:
            logger.warning("block parse failed: block_id=%s", block_id, exc_info=True)
            return None, f"{type(exc).__name__}: {exc}"
    return None, "unreachable"
