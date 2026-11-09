"""Sandbox abstraction: the seam between the execution service and E2B."""

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import ClassVar, Protocol

from app.domain import ErrorCategory


@dataclass(frozen=True)
class RunOutput:
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    exit_code: int | None
    timed_out: bool
    duration_ms: int


class SandboxSession(Protocol):
    sandbox_id: str

    async def run_python(self, code: str, timeout_seconds: int) -> RunOutput:
        """Run code. A user-code timeout is returned (timed_out=True), never raised.

        Raises SandboxError subclasses for infrastructure failures.
        """
        ...


class SandboxBackend(Protocol):
    def session(self, lifetime_seconds: int) -> AbstractAsyncContextManager[SandboxSession]:
        """Create a sandbox that lives for at most lifetime_seconds; destroy it on exit."""
        ...


class SandboxError(Exception):
    category: ClassVar[ErrorCategory] = ErrorCategory.INTERNAL_ERROR


class SandboxUnavailableError(SandboxError):
    category = ErrorCategory.SANDBOX_UNAVAILABLE


class SandboxAuthError(SandboxError):
    category = ErrorCategory.AUTH_ERROR


class SandboxUpstreamError(SandboxError):
    category = ErrorCategory.UPSTREAM_ERROR
