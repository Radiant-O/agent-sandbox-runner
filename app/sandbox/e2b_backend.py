"""E2B implementation of the sandbox backend.

SDK calls used here were verified against e2b 2.63.0 (see docs/design.md).
"""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx
from e2b import (
    AsyncSandbox,
    AuthenticationException,
    CommandExitException,
    RateLimitException,
    SandboxException,
    SandboxNotRunningException,
    SandboxUnreachableException,
    ServiceBusyException,
    TimeoutException,
)
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import Settings
from app.core.metrics import Metrics
from app.sandbox.base import (
    RunOutput,
    SandboxAuthError,
    SandboxSession,
    SandboxUnavailableError,
    SandboxUpstreamError,
)
from app.sandbox.events import emit
from app.sandbox.output import OutputBuffer

log = logging.getLogger(__name__)

SCRIPT_PATH = "/home/user/main.py"
RUN_COMMAND = f"python3 {SCRIPT_PATH}"
# A TimeoutException earlier than this fraction of the user's timeout is infrastructure.
USER_TIMEOUT_TOLERANCE = 0.9

# Only these are worth retrying for sandbox *creation*. Code execution is never retried.
_TRANSIENT_CREATE_ERRORS = (
    RateLimitException,
    ServiceBusyException,
    SandboxUnreachableException,
    httpx.TransportError,
)


def _ms_since(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


class E2BSession:
    def __init__(
        self, sandbox: Any, max_output_bytes: int, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._sbx = sandbox
        self._max_output = max_output_bytes
        self._clock = clock
        self.sandbox_id: str = sandbox.sandbox_id

    async def run_python(self, code: str, timeout_seconds: int) -> RunOutput:
        out = OutputBuffer(self._max_output)
        err = OutputBuffer(self._max_output)
        start = self._clock()

        def on_stdout(chunk: str) -> None:
            accepted = out.append(chunk)
            if accepted:
                emit("stdout", data=accepted)

        def on_stderr(chunk: str) -> None:
            accepted = err.append(chunk)
            if accepted:
                emit("stderr", data=accepted)

        try:
            await self._sbx.files.write(SCRIPT_PATH, code)
            emit("code_uploaded", upload_ms=int((self._clock() - start) * 1000))
        except AuthenticationException as e:
            raise SandboxAuthError("E2B rejected the credentials") from e
        except Exception as e:
            # The code never ran, so no failure here can be the user's fault.
            raise SandboxUpstreamError(f"Could not upload code: {type(e).__name__}: {e}") from e

        exit_code: int | None = None
        timed_out = False
        run_start = self._clock()
        try:
            result = await self._sbx.commands.run(
                RUN_COMMAND,
                timeout=timeout_seconds,
                on_stdout=on_stdout,
                on_stderr=on_stderr,
                # Without this the SDK keeps its own uncapped copy of all output in memory.
                retain_output=False,
            )
            exit_code = result.exit_code
        except CommandExitException as e:
            # Non-zero exit: the user's code failed. That is a result, not an infra error.
            exit_code = e.exit_code
        except (SandboxNotRunningException, SandboxUnreachableException) as e:
            # Must precede TimeoutException: both subclass it in the SDK.
            raise SandboxUpstreamError(f"Sandbox stopped responding: {e}") from e
        except TimeoutException as e:
            # The SDK also raises plain TimeoutException for gRPC CANCELED (sandbox shut
            # down) and stream-open timeouts. Only blame the user's code if its time was
            # actually used up.
            elapsed = self._clock() - start
            if elapsed < timeout_seconds * USER_TIMEOUT_TOLERANCE:
                raise SandboxUpstreamError(
                    f"Execution interrupted after {elapsed:.1f}s of {timeout_seconds}s: {e}"
                ) from e
            timed_out = True
        except AuthenticationException as e:
            raise SandboxAuthError("E2B rejected the credentials") from e
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # SandboxException, ServiceBusyException (not a SandboxException), transport
            # errors, and bare Exceptions raised by the SDK's stream handling.
            raise SandboxUpstreamError(f"E2B error during execution: {type(e).__name__}") from e
        run_ms = int((self._clock() - run_start) * 1000)
        emit("exited", exit_code=exit_code, timed_out=timed_out, run_ms=run_ms)
        return RunOutput(
            stdout=out.text,
            stderr=err.text,
            stdout_truncated=out.truncated,
            stderr_truncated=err.truncated,
            exit_code=exit_code,
            timed_out=timed_out,
            duration_ms=int((self._clock() - start) * 1000),
        )


class E2BSandboxBackend:
    def __init__(
        self,
        settings: Settings,
        metrics: Metrics,
        sandbox_cls: Any = AsyncSandbox,
        retry_wait_seconds: float = 0.5,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._clock = clock
        self._settings = settings
        self._metrics = metrics
        self._sandbox_cls = sandbox_cls
        self._retry_wait = retry_wait_seconds

    def _on_retry(self, state: RetryCallState) -> None:
        self._metrics.create_retried()
        exc = state.outcome.exception() if state.outcome else None
        log.warning(
            "sandbox create failed, retrying",
            extra={"attempt": state.attempt_number, "error": type(exc).__name__},
        )

    async def _create(self, lifetime_seconds: int) -> Any:
        key = self._settings.E2B_API_KEY
        if key is None or not key.get_secret_value():
            raise SandboxAuthError("E2B_API_KEY is not configured")
        start = time.monotonic()
        # One key per logical create, reused by every retry: if a response is lost after
        # E2B created the sandbox, the retry gets that sandbox instead of a second one.
        idempotency_key = uuid.uuid4().hex
        try:
            async for attempt in AsyncRetrying(
                retry=retry_if_exception_type(_TRANSIENT_CREATE_ERRORS),
                stop=stop_after_attempt(self._settings.SANDBOX_CREATE_RETRIES),
                wait=wait_exponential(multiplier=self._retry_wait, max=4 * self._retry_wait),
                before_sleep=self._on_retry,
                reraise=False,
            ):
                with attempt:
                    sbx = await self._sandbox_cls.create(
                        template=self._settings.SANDBOX_TEMPLATE,
                        timeout=lifetime_seconds,
                        allow_internet_access=self._settings.SANDBOX_ALLOW_INTERNET,
                        envs={},  # never pass server secrets into untrusted code
                        metadata={"app": "agent-sandbox-runner"},
                        api_key=key.get_secret_value(),
                        idempotency_key=idempotency_key,
                    )
        except RetryError as e:
            cause = e.last_attempt.exception()
            raise SandboxUnavailableError(
                f"Could not create sandbox after {self._settings.SANDBOX_CREATE_RETRIES} "
                f"attempts: {type(cause).__name__}"
            ) from cause
        except AuthenticationException as e:
            raise SandboxAuthError("E2B rejected the credentials") from e
        except (SandboxException, httpx.HTTPError) as e:
            raise SandboxUnavailableError(f"Could not create sandbox: {e}") from e
        create_ms = _ms_since(start)
        self._metrics.sandbox_created(create_ms)
        emit("sandbox_created", sandbox_id=sbx.sandbox_id, create_ms=create_ms)
        log.info("sandbox created", extra={"sandbox_id": sbx.sandbox_id, "create_ms": create_ms})
        return sbx

    @asynccontextmanager
    async def session(self, lifetime_seconds: int) -> AsyncIterator[SandboxSession]:
        emit("sandbox_creating")
        sbx = await self._create(lifetime_seconds)
        try:
            yield E2BSession(sbx, self._settings.MAX_OUTPUT_BYTES, self._clock)
        finally:
            kill_start = time.monotonic()
            try:
                await sbx.kill()
                self._metrics.sandbox_killed()
                emit("sandbox_killed", sandbox_id=sbx.sandbox_id, kill_ms=_ms_since(kill_start))
                log.info("sandbox killed", extra={"sandbox_id": sbx.sandbox_id})
            except Exception:
                # The lifetime timeout set at create() is the backstop: E2B destroys it anyway.
                self._metrics.cleanup_failed()
                emit("cleanup_failed", sandbox_id=sbx.sandbox_id)
                log.exception(
                    "sandbox kill failed; relying on lifetime timeout",
                    extra={"sandbox_id": sbx.sandbox_id, "lifetime_seconds": lifetime_seconds},
                )
