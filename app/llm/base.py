"""Provider-neutral LLM interface used by the agent."""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON string as produced by the model; validated by the agent


@dataclass(frozen=True)
class LLMTurn:
    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    total_tokens: int = 0


class LLMError(Exception):
    """The LLM provider failed (network, auth, quota, malformed response)."""


class LLMProvider(Protocol):
    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], max_tokens: int
    ) -> LLMTurn: ...
