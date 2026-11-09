from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest

from app.llm.base import LLMError
from app.llm.openai_compat import OpenAICompatibleProvider

KEY = "sk-or-secret-123"


class StubCompletions:
    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


def stub_client(completions: StubCompletions) -> Any:
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


def response(message: Any, finish: str = "stop", tokens: int = 42) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish)],
        usage=SimpleNamespace(total_tokens=tokens),
    )


def provider(c: StubCompletions) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        api_key=KEY, base_url="https://x", model="m", client=stub_client(c)
    )


async def test_maps_tool_calls() -> None:
    tc = SimpleNamespace(
        id="call_1",
        type="function",
        function=SimpleNamespace(name="execute_python", arguments='{"code": "print(1)"}'),
    )
    c = StubCompletions(response(SimpleNamespace(content=None, tool_calls=[tc]), "tool_calls"))
    turn = await provider(c).complete([{"role": "user", "content": "hi"}], [{"t": 1}], 100)
    assert turn.text is None
    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0].id == "call_1"
    assert turn.tool_calls[0].name == "execute_python"
    assert turn.tool_calls[0].arguments == '{"code": "print(1)"}'
    assert turn.finish_reason == "tool_calls"
    assert turn.total_tokens == 42
    sent = c.calls[0]
    assert sent["model"] == "m" and sent["max_tokens"] == 100
    assert sent["tools"] == [{"t": 1}] and sent["tool_choice"] == "auto"


async def test_maps_text_only_turn() -> None:
    c = StubCompletions(response(SimpleNamespace(content="The answer is 4.", tool_calls=None)))
    turn = await provider(c).complete([], [], 50)
    assert turn.text == "The answer is 4."
    assert turn.tool_calls == []


async def test_api_error_wrapped_without_key() -> None:
    err = openai.APIConnectionError(
        message=f"failed with key {KEY}", request=httpx.Request("POST", "http://x")
    )
    with pytest.raises(LLMError) as ei:
        await provider(StubCompletions(error=err)).complete([], [], 10)
    assert KEY not in str(ei.value)


async def test_empty_choices_is_llm_error() -> None:
    c = StubCompletions(SimpleNamespace(choices=[], usage=None))
    with pytest.raises(LLMError):
        await provider(c).complete([], [], 10)
