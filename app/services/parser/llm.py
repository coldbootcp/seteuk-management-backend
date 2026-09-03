import json
import logging

from openai import AsyncOpenAI

from app.schemas.seteuk import LLMActivityDraftList
from app.services.llm import get_provider

__all__ = ["get_provider", "parse_block"]

logger = logging.getLogger(__name__)


async def parse_block(
    client: AsyncOpenAI, system_prompt: str, block_id: str, block_text: str
) -> tuple[LLMActivityDraftList | None, str | None]:
    """Block-level exception handling per docs/PARSER_SPEC.md 2.5 — no retries; a failing
    block is dropped from the result and logged, the rest of the batch keeps going."""
    try:
        raw = await client.complete_json(system_prompt, block_text)
        return LLMActivityDraftList.model_validate(json.loads(raw)), None
    except Exception as exc:
        logger.warning("block parse failed: block_id=%s", block_id, exc_info=True)
        return None, f"{type(exc).__name__}: {exc}"
