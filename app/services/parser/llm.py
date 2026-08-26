import json
import logging

from openai import AsyncOpenAI

from app.core.config import get_settings
from app.schemas.seteuk import LLMActivityDraftList

logger = logging.getLogger(__name__)
settings = get_settings()


def build_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        max_retries=0,
    )


async def call_deepseek(client: AsyncOpenAI, system_prompt: str, block_text: str) -> str:
    response = await client.chat.completions.create(
        model=settings.deepseek_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": block_text},
        ],
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content or ""


async def parse_block(
    client: AsyncOpenAI, system_prompt: str, block_id: str, block_text: str
) -> tuple[LLMActivityDraftList | None, str | None]:
    """Block-level exception handling per docs/PARSER_SPEC.md 2.5 — no retries; a failing
    block is dropped from the result and logged, the rest of the batch keeps going."""
    try:
        raw = await call_deepseek(client, system_prompt, block_text)
        return LLMActivityDraftList.model_validate(json.loads(raw)), None
    except Exception as exc:
        logger.warning("block parse failed: block_id=%s", block_id, exc_info=True)
        return None, f"{type(exc).__name__}: {exc}"
