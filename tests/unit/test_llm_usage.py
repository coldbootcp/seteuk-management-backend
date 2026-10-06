"""AI 토큰 사용량 기록 — 생각 토큰 계산과, 사용량만 담긴 스트림 조각 처리."""

from types import SimpleNamespace
from typing import Any

import pytest

from app.services.llm import provider as provider_module
from app.services.llm.usage import usage_numbers


def test_gemini_thinking_tokens_come_from_total() -> None:
    usage = SimpleNamespace(prompt_tokens=3, completion_tokens=9, total_tokens=103)
    assert usage_numbers(usage) == {
        "input_tokens": 3,
        "output_tokens": 9,
        "thinking_tokens": 91,
        "cached_input_tokens": 0,
    }


def test_reported_reasoning_tokens_are_split_out_of_output() -> None:
    usage = SimpleNamespace(
        prompt_tokens=10,
        completion_tokens=50,
        total_tokens=60,
        completion_tokens_details=SimpleNamespace(reasoning_tokens=30),
        prompt_tokens_details=SimpleNamespace(cached_tokens=4),
    )
    assert usage_numbers(usage) == {
        "input_tokens": 10,
        "output_tokens": 20,
        "thinking_tokens": 30,
        "cached_input_tokens": 4,
    }


class _FakeStream:
    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = chunks

    def __aiter__(self) -> "_FakeStream":
        self._iter = iter(self._chunks)
        return self

    async def __anext__(self) -> Any:
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration from None


async def test_stream_hides_usage_only_chunk_and_records_last_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    final_usage = SimpleNamespace(prompt_tokens=5, completion_tokens=2, total_tokens=7)
    chunks = [
        SimpleNamespace(choices=[SimpleNamespace(delta="a")], usage=None),
        SimpleNamespace(choices=[], usage=final_usage),
    ]
    recorded: list[tuple[str, Any]] = []

    async def _record(provider: str, model: str, kind: str, usage: Any) -> None:
        recorded.append((kind, usage))

    async def _create(**kwargs: Any) -> _FakeStream:
        assert kwargs["stream_options"] == {"include_usage": True}
        return _FakeStream(chunks)

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))
    llm = provider_module.OpenAICompatibleProvider(api_key="k", base_url="http://x", model="m")
    monkeypatch.setattr(llm, "_client", lambda: client)
    monkeypatch.setattr(provider_module, "record_usage", _record)

    received = [chunk async for chunk in llm.stream([{"role": "user", "content": "hi"}], None)]

    assert len(received) == 1
    assert recorded == [("stream", final_usage)]
