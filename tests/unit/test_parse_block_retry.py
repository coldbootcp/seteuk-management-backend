import json

import pytest
from openai import APITimeoutError

from app.services.parser.llm import parse_block


class _FakeClient:
    """complete_json이 정해진 순서대로 던지거나 돌려주는 가짜 프로바이더."""

    def __init__(self, outcomes: list) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    async def complete_json(self, system_prompt: str, user_content: str) -> str:
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _timeout() -> APITimeoutError:
    return APITimeoutError(request=None)  # type: ignore[arg-type]


_VALID = json.dumps(
    {
        "items": [
            {
                "activity_name": "탐구",
                "activity_type": "report",
                "description": "내용",
                "keywords": [],
            }
        ]
    }
)


@pytest.mark.parametrize("failures", [1, 2])
async def test_transient_failures_are_retried(monkeypatch, failures: int) -> None:
    """타임아웃으로 블록이 통째로 버려지면 활동 수십 건이 조용히 사라진다.
    실제 생기부 검증에서 156건이 97건으로 줄어든 원인이었다."""
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    client = _FakeClient([_timeout()] * failures + [_VALID])

    draft, error = await parse_block(client, "sys", "block-1", "본문")

    assert error is None
    assert draft is not None and len(draft.items) == 1
    assert client.calls == failures + 1


async def test_transient_failures_give_up_after_three_attempts(monkeypatch) -> None:
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    client = _FakeClient([_timeout()] * 3)

    draft, error = await parse_block(client, "sys", "block-1", "본문")

    assert draft is None
    assert error is not None and "APITimeoutError" in error
    assert client.calls == 3


async def test_malformed_output_is_not_retried(monkeypatch) -> None:
    """스키마에 맞지 않는 응답은 다시 물어도 같은 답이 온다 — 그건 프롬프트
    문제이지 일시적인 사정이 아니다(PARSER_SPEC 2.5)."""
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    client = _FakeClient(['{"items": [{"없는필드": 1}]}'])

    draft, error = await parse_block(client, "sys", "block-1", "본문")

    assert draft is None and error
    assert client.calls == 1


async def _no_sleep(_seconds: float) -> None:
    return None


async def test_a_missing_description_does_not_discard_the_whole_block(monkeypatch) -> None:
    """항목 하나가 description을 빠뜨렸다고 블록 전체(활동 수십 건)를 버리면 안 된다.
    activity_type이 enum 밖의 값일 때 이미 같은 결론을 냈다."""
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    payload = json.dumps(
        {
            "items": [
                {"activity_name": "설명 빠진 활동", "activity_type": "report"},
                {"activity_name": "멀쩡한 활동", "activity_type": "report", "description": "내용"},
            ]
        }
    )
    client = _FakeClient([payload])

    draft, error = await parse_block(client, "sys", "block-1", "본문")

    assert error is None
    assert draft is not None
    assert [i.activity_name for i in draft.items] == ["설명 빠진 활동", "멀쩡한 활동"]
    assert draft.items[0].description == ""
