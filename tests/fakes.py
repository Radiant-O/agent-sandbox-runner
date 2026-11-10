"""Deterministic test doubles for the sandbox backend (and, later, the LLM)."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.sandbox.base import RunOutput, SandboxSession
from app.sandbox.events import emit

OK = RunOutput(
    stdout="ok\n",
    stderr="",
    stdout_truncated=False,
    stderr_truncated=False,
    exit_code=0,
    timed_out=False,
    duration_ms=1,
)


class FakeSession:
    def __init__(self, backend: "FakeSandboxBackend", sandbox_id: str) -> None:
        self._backend = backend
        self.sandbox_id = sandbox_id

    async def run_python(self, code: str, timeout_seconds: int) -> RunOutput:
        self._backend.codes.append(code)
        emit("code_uploaded", upload_ms=1)
        if self._backend.delay:
            await asyncio.sleep(self._backend.delay)
        nxt = self._backend.outputs.pop(0) if self._backend.outputs else OK
        if isinstance(nxt, Exception):
            raise nxt
        if nxt.stdout:
            emit("stdout", data=nxt.stdout)
        if nxt.stderr:
            emit("stderr", data=nxt.stderr)
        emit("exited", exit_code=nxt.exit_code, timed_out=nxt.timed_out, run_ms=nxt.duration_ms)
        return nxt


class FakeSandboxBackend:
    def __init__(
        self,
        outputs: list[RunOutput | Exception] | None = None,
        create_error: Exception | None = None,
        delay: float = 0,
    ) -> None:
        self.outputs = list(outputs or [])
        self.create_error = create_error
        self.delay = delay
        self.created = 0
        self.killed = 0
        self.live = 0
        self.max_live = 0
        self.lifetimes: list[int] = []
        self.codes: list[str] = []

    @asynccontextmanager
    async def session(self, lifetime_seconds: int) -> AsyncIterator[SandboxSession]:
        emit("sandbox_creating")
        if self.create_error is not None:
            raise self.create_error
        self.created += 1
        emit("sandbox_created", sandbox_id=f"fake-sbx-{self.created}", create_ms=1)
        self.lifetimes.append(lifetime_seconds)
        self.live += 1
        self.max_live = max(self.max_live, self.live)
        try:
            yield FakeSession(self, f"fake-sbx-{self.created}")
        finally:
            self.live -= 1
            self.killed += 1
            emit("sandbox_killed", sandbox_id=f"fake-sbx-{self.created}", kill_ms=1)


# ---- LLM ---------------------------------------------------------------------

from typing import Any  # noqa: E402

from app.llm.base import LLMTurn  # noqa: E402


class ScriptedLLM:
    """Returns pre-scripted turns in order; records every request it received."""

    def __init__(self, turns: list[LLMTurn | Exception], repeat_last: bool = False) -> None:
        self.turns = list(turns)
        self.repeat_last = repeat_last
        self.requests: list[list[dict[str, Any]]] = []
        self.tools: list[list[dict[str, Any]]] = []

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], max_tokens: int
    ) -> LLMTurn:
        self.requests.append([dict(m) for m in messages])
        self.tools.append(tools)
        if not self.turns:
            raise AssertionError("ScriptedLLM ran out of turns")
        nxt = self.turns[0] if (self.repeat_last and len(self.turns) == 1) else self.turns.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt
