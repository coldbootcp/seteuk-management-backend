"""Gemini는 도구 호출에 생각 서명(extra_content)을 붙이고, 되돌려 보낼 때 빠지면 400을 낸다."""

from types import SimpleNamespace

from app.services.chat_service import _assistant_tool_calls, _merge_tool_call_deltas


def _delta(index: int, **kwargs: object) -> SimpleNamespace:
    function = SimpleNamespace(
        name=kwargs.pop("name", None), arguments=kwargs.pop("arguments", None)
    )
    return SimpleNamespace(index=index, id=kwargs.pop("id", None), function=function, **kwargs)


def test_thought_signature_is_kept_and_sent_back() -> None:
    signature = {"google": {"thought_signature": "sig-abc"}}
    acc: dict = {}
    first = _delta(0, id="call_1", name="lookup", arguments='{"a"', extra_content=signature)
    _merge_tool_call_deltas(acc, [first])
    _merge_tool_call_deltas(acc, [_delta(0, arguments=": 1}")])

    [call] = _assistant_tool_calls(acc)
    assert call["function"] == {"name": "lookup", "arguments": '{"a": 1}'}
    assert call["extra_content"] == signature


def test_providers_without_signatures_send_plain_tool_calls() -> None:
    acc: dict = {}
    _merge_tool_call_deltas(acc, [_delta(0, id="call_1", name="lookup", arguments="{}")])

    [call] = _assistant_tool_calls(acc)
    assert "extra_content" not in call
