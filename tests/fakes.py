"""Deterministic test doubles for the sandbox backend (and, later, the LLM)."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.sandbox.base import RunOutput, SandboxSession

OK = RunOutput(
    stdout="ok\n", stderr="", stdout_truncated=False, stderr_truncated=False,
    exit_code=0, timed_out=False, duration_ms=1,
)


class FakeSession:
    def __init__(self, backend: "FakeSandboxBackend", sandbox_id: str) -> None:
        self._backend = backend
        self.sandbox_id = sandbox_id

    async def run_python(self, code: str, timeout_seconds: int) -> RunOutput:
        self._backend.codes.append(code)
        if self._backend.delay:
            await asyncio.sleep(self._backend.delay)
        nxt = self._backend.outputs.pop(0) if self._backend.outputs else OK
        if isinstance(nxt, Exception):
            raise nxt
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
        if self.create_error is not None:
            raise self.create_error
        self.created += 1
        self.lifetimes.append(lifetime_seconds)
        self.live += 1
        self.max_live = max(self.max_live, self.live)
        try:
            yield FakeSession(self, f"fake-sbx-{self.created}")
        finally:
            self.live -= 1
            self.killed += 1
