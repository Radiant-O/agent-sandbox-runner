"""OpenAI-compatible chat-completions provider (used with OpenRouter to reach Claude)."""

from typing import Any

import openai
from openai import AsyncOpenAI

from app.llm.base import LLMError, LLMTurn, ToolCall


class OpenAICompatibleProvider:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 60,
        client: Any | None = None,
    ) -> None:
        self._model = model
        # Typed as Any: we pass plain-dict messages (provider-neutral), not the SDK TypedDicts.
        self._client: Any = client or AsyncOpenAI(
            api_key=api_key, base_url=base_url, timeout=timeout_seconds, max_retries=2
        )

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], max_tokens: int
    ) -> LLMTurn:
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                max_tokens=max_tokens,
            )
        except openai.APIStatusError as e:
            # Status + type only: provider messages can echo request details.
            raise LLMError(f"LLM provider returned HTTP {e.status_code}") from None
        except openai.APIError as e:
            raise LLMError(f"LLM provider request failed: {type(e).__name__}") from None

        if not getattr(resp, "choices", None):
            raise LLMError("LLM provider returned no choices")
        choice = resp.choices[0]
        msg = choice.message
        calls = [
            ToolCall(id=tc.id, name=tc.function.name, arguments=tc.function.arguments or "")
            for tc in (msg.tool_calls or [])
            if getattr(tc, "function", None) is not None
        ]
        usage = getattr(resp, "usage", None)
        return LLMTurn(
            text=msg.content or None,
            tool_calls=calls,
            finish_reason=choice.finish_reason or "stop",
            total_tokens=getattr(usage, "total_tokens", 0) or 0,
        )
