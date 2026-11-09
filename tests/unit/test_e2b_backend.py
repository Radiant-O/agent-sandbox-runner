"""E2B backend tests against a scripted stand-in for e2b.AsyncSandbox (no network)."""

import re
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from e2b import (
    AuthenticationException,
    CommandExitException,
    CommandResult,
    RateLimitException,
    SandboxException,
    SandboxNotRunningException,
    ServiceBusyException,
    TimeoutException,
)
from pydantic import SecretStr

from app.core.config import Settings
from app.core.metrics import Metrics
from app.sandbox.base import (
    RunOutput,
    SandboxAuthError,
    SandboxUnavailableError,
    SandboxUpstreamError,
)
from app.sandbox.e2b_backend import E2BSandboxBackend


class Script:
    """What the fake sandbox should do, and what it observed."""

    def __init__(self) -> None:
        self.create_errors: list[Exception] = []
        self.chunks_out: list[str] = ["ok\n"]
        self.chunks_err: list[str] = []
        self.run_result: BaseException | None = None  # raised after streaming
        self.kill_error: Exception | None = None
        self.create_calls: list[dict[str, Any]] = []
        self.kill_calls = 0
        self.written: dict[str, str] = {}
        self.run_calls: list[dict[str, Any]] = []
        self.write_error: BaseException | None = None
        self.now = 0.0  # fake monotonic clock
        self.run_elapsed = 0.0  # how long commands.run "takes"


def make_sandbox_cls(script: Script) -> type:
    class FakeFiles:
        async def write(self, path: str, data: str) -> None:
            if script.write_error is not None:
                raise script.write_error
            script.written[path] = data

    class FakeCommands:
        async def run(
            self,
            cmd: str,
            timeout: float,  # noqa: ASYNC109 - mirrors the SDK signature
            on_stdout: Callable[[str], None],
            on_stderr: Callable[[str], None],
            **kw: Any,
        ) -> CommandResult:  # type: ignore[type-arg]
            script.run_calls.append({"cmd": cmd, "timeout": timeout, **kw})
            script.now += script.run_elapsed
            for c in script.chunks_out:
                on_stdout(c)
            for c in script.chunks_err:
                on_stderr(c)
            if script.run_result is not None:
                raise script.run_result
            return CommandResult(stdout="IGNORED", stderr="", exit_code=0, error=None)

    class FakeAsyncSandbox:
        def __init__(self) -> None:
            self.sandbox_id = "sbx-test"
            self.files = FakeFiles()
            self.commands = FakeCommands()

        @classmethod
        async def create(cls, **kwargs: Any) -> "FakeAsyncSandbox":
            script.create_calls.append(kwargs)
            if script.create_errors:
                raise script.create_errors.pop(0)
            return cls()

        async def kill(self) -> bool:
            script.kill_calls += 1
            if script.kill_error is not None:
                raise script.kill_error
            return True

    return FakeAsyncSandbox


@pytest.fixture
def script() -> Script:
    return Script()


@pytest.fixture
def metrics() -> Metrics:
    return Metrics()


@pytest.fixture
def backend(settings: Settings, script: Script, metrics: Metrics) -> E2BSandboxBackend:
    settings.E2B_API_KEY = SecretStr("e2b-test")
    settings.MAX_OUTPUT_BYTES = 1024
    return E2BSandboxBackend(
        settings,
        metrics,
        sandbox_cls=make_sandbox_cls(script),
        retry_wait_seconds=0,
        clock=lambda: script.now,
    )


async def _run(
    backend: E2BSandboxBackend, code: str = "print('ok')", timeout_s: int = 5
) -> RunOutput:
    async with backend.session(lifetime_seconds=65) as s:
        return await s.run_python(code, timeout_s)


async def test_success_returns_exit_zero_and_output(
    backend: E2BSandboxBackend, script: Script
) -> None:
    out = await _run(backend)
    assert out.exit_code == 0
    assert out.stdout == "ok\n"  # from the stream, not the result object
    assert out.timed_out is False
    assert script.written == {"/home/user/main.py": "print('ok')"}
    assert script.run_calls[0]["cmd"] == "python3 /home/user/main.py"
    assert script.run_calls[0]["timeout"] == 5


async def test_nonzero_exit_is_output_not_exception(
    backend: E2BSandboxBackend, script: Script
) -> None:
    script.chunks_out = []
    script.chunks_err = ["Traceback...\nZeroDivisionError: x\n"]
    script.run_result = CommandExitException(
        stdout="", stderr="ZeroDivisionError: x", exit_code=1, error=None
    )
    out = await _run(backend, "1/0")
    assert out.exit_code == 1
    assert "ZeroDivisionError" in out.stderr
    assert out.timed_out is False


async def test_timeout_returns_timed_out_with_partial_output(
    backend: E2BSandboxBackend, script: Script
) -> None:
    script.chunks_out = ["partial\n"]
    script.run_elapsed = 5.0  # the user's full timeout really elapsed
    script.run_result = TimeoutException("deadline_exceeded")
    out = await _run(backend)
    assert out.timed_out is True
    assert out.exit_code is None
    assert out.stdout == "partial\n"


async def test_sandbox_not_running_is_upstream_not_timeout(
    backend: E2BSandboxBackend, script: Script
) -> None:
    script.run_result = SandboxNotRunningException("sandbox gone")
    with pytest.raises(SandboxUpstreamError):
        await _run(backend)


async def test_network_drop_mid_run_is_upstream_error(
    backend: E2BSandboxBackend, script: Script
) -> None:
    script.run_result = httpx.RemoteProtocolError("peer closed")
    with pytest.raises(SandboxUpstreamError):
        await _run(backend)


async def test_other_sandbox_exception_mid_run_is_upstream(
    backend: E2BSandboxBackend, script: Script
) -> None:
    script.run_result = SandboxException("boom")
    with pytest.raises(SandboxUpstreamError):
        await _run(backend)


async def test_create_retries_transient_then_succeeds(
    backend: E2BSandboxBackend, script: Script, metrics: Metrics
) -> None:
    script.create_errors = [RateLimitException("slow down"), RateLimitException("slow down")]
    out = await _run(backend)
    assert out.exit_code == 0
    assert len(script.create_calls) == 3
    assert metrics.snapshot()["create_retries_total"] == 2


async def test_create_retries_exhausted_is_unavailable(
    backend: E2BSandboxBackend, script: Script
) -> None:
    script.create_errors = [RateLimitException("x") for _ in range(5)]
    with pytest.raises(SandboxUnavailableError):
        await _run(backend)
    assert len(script.create_calls) == 3


async def test_create_auth_error_not_retried(backend: E2BSandboxBackend, script: Script) -> None:
    script.create_errors = [AuthenticationException("bad key")]
    with pytest.raises(SandboxAuthError):
        await _run(backend)
    assert len(script.create_calls) == 1


async def test_missing_e2b_key_fails_before_network(
    settings: Settings, script: Script, metrics: Metrics
) -> None:
    settings.E2B_API_KEY = None
    b = E2BSandboxBackend(settings, metrics, sandbox_cls=make_sandbox_cls(script))
    with pytest.raises(SandboxAuthError):
        await _run(b)
    assert script.create_calls == []


async def test_kill_called_on_success_and_on_error(
    backend: E2BSandboxBackend, script: Script
) -> None:
    await _run(backend)
    script.run_result = SandboxException("boom")
    with pytest.raises(SandboxUpstreamError):
        await _run(backend)
    assert script.kill_calls == 2


async def test_kill_failure_is_swallowed_and_counted(
    backend: E2BSandboxBackend, script: Script, metrics: Metrics
) -> None:
    script.kill_error = SandboxException("kill failed")
    out = await _run(backend)
    assert out.exit_code == 0
    snap = metrics.snapshot()
    assert snap["cleanup_failures_total"] == 1
    assert snap["sandboxes_live"] == 0


async def test_output_capped(backend: E2BSandboxBackend, script: Script) -> None:
    script.chunks_out = ["y" * 1000] * 5000  # ~5 MB
    out = await _run(backend)
    assert out.stdout_truncated is True
    assert len(out.stdout.encode()) == 1024


async def test_sandbox_envs_empty_and_internet_off(
    backend: E2BSandboxBackend, script: Script
) -> None:
    await _run(backend)
    kw = script.create_calls[0]
    assert kw["envs"] == {}
    assert kw["allow_internet_access"] is False
    assert kw["timeout"] == 65
    assert kw["api_key"] == "e2b-test"


# ---- final-review fixes ------------------------------------------------------


async def test_sdk_does_not_retain_output(backend: E2BSandboxBackend, script: Script) -> None:
    """C1: the SDK must not accumulate a second, uncapped copy of the output."""
    await _run(backend)
    assert script.run_calls[0]["retain_output"] is False


async def test_early_timeout_exception_is_upstream_not_user_timeout(
    backend: E2BSandboxBackend, script: Script
) -> None:
    """I1: e.g. gRPC CANCELED when E2B shuts the sandbox down: not the user's timeout."""
    script.run_elapsed = 0.5
    script.run_result = TimeoutException("canceled: sandbox shut down")
    with pytest.raises(SandboxUpstreamError):
        await _run(backend, timeout_s=5)


async def test_file_write_timeout_is_upstream(backend: E2BSandboxBackend, script: Script) -> None:
    """I1: the code never ran, so this cannot be a user-code timeout."""
    script.write_error = TimeoutException("Request timed out")
    with pytest.raises(SandboxUpstreamError):
        await _run(backend)


async def test_unknown_sdk_exception_mid_run_is_upstream(
    backend: E2BSandboxBackend, script: Script
) -> None:
    """I1/M3: ServiceBusyException is not a SandboxException; bare Exceptions happen too."""
    script.run_result = ServiceBusyException("503")
    with pytest.raises(SandboxUpstreamError):
        await _run(backend)
    script.run_result = Exception("Command ended without an end event")
    with pytest.raises(SandboxUpstreamError):
        await _run(backend)


async def test_create_uses_one_idempotency_key_across_retries(
    backend: E2BSandboxBackend, script: Script
) -> None:
    """I4: a retried create after a lost response must not spawn a second sandbox."""
    script.create_errors = [httpx.ReadTimeout("lost response")]
    await _run(backend)
    keys = [c["idempotency_key"] for c in script.create_calls]
    assert len(keys) == 2 and keys[0] == keys[1]
    assert re.fullmatch(r"[a-z0-9-]{1,255}", keys[0])
    await _run(backend)
    assert script.create_calls[-1]["idempotency_key"] != keys[0]  # new logical create
