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


def test_calls_without_index_are_kept_apart() -> None:
    """Gemini는 index를 None으로 보낸다 — 한 답변의 두 호출이 한 칸으로 합쳐지면 안 된다."""
    acc: dict = {}
    _merge_tool_call_deltas(
        acc,
        [
            _delta(
                None, id="a", name="resolve_record_conflict", arguments='{"choice": "use_record"}'
            ),
            _delta(None, id="b", name="signal_ready_to_conclude", arguments="{}"),
        ],
    )

    calls = _assistant_tool_calls(acc)
    assert [c["function"]["name"] for c in calls] == [
        "resolve_record_conflict",
        "signal_ready_to_conclude",
    ]
    assert [c["function"]["arguments"] for c in calls] == ['{"choice": "use_record"}', "{}"]


def test_index_less_fragments_continue_the_previous_call() -> None:
    acc: dict = {}
    _merge_tool_call_deltas(acc, [_delta(None, id="a", name="lookup", arguments='{"a"')])
    _merge_tool_call_deltas(acc, [_delta(None, arguments=": 1}")])

    [call] = _assistant_tool_calls(acc)
    assert call["function"]["arguments"] == '{"a": 1}'
