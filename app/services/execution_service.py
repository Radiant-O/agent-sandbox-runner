"""Execution service: policy, concurrency, lifecycle, classification and persistence.

Every code execution — from the REST API or from the agent — goes through here.
"""

import asyncio
import functools
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from app.core.config import Settings
from app.core.logging import execution_id_var
from app.core.metrics import Metrics
from app.domain import ErrorCategory, ExecutionRecord, ExecutionStatus, utcnow
from app.sandbox.base import RunOutput, SandboxBackend, SandboxError, SandboxSession
from app.sandbox.events import EventSink, current_sink, sink_scope
from app.schemas.executions import ExecutionOut
from app.services.events import EventBus
from app.store import ExecutionStore

log = logging.getLogger(__name__)

SANDBOX_LIFETIME_GRACE_SECONDS = 60
WAIT_GRACE_SECONDS = 30

_EXC_LINE = re.compile(r"^([A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt|Warning))\b")


class PolicyViolation(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def parse_exception_type(stderr: str) -> str | None:
    """Exception class name from the last line of a Python traceback, if any."""
    for line in reversed(stderr.strip().splitlines()):
        line = line.strip()
        if line:
            m = _EXC_LINE.match(line)
            return m.group(1) if m else None
    return None


def apply_output(rec: ExecutionRecord, out: RunOutput) -> None:
    rec.stdout = out.stdout
    rec.stderr = out.stderr
    rec.stdout_truncated = out.stdout_truncated
    rec.stderr_truncated = out.stderr_truncated
    rec.exit_code = out.exit_code
    if out.timed_out:
        rec.status = ExecutionStatus.TIMED_OUT
        rec.error_category = ErrorCategory.TIMEOUT
        rec.error_message = f"Execution exceeded {rec.timeout_seconds}s timeout"
    elif out.exit_code == 0:
        rec.status = ExecutionStatus.SUCCEEDED
    else:
        rec.status = ExecutionStatus.FAILED
        rec.error_category = ErrorCategory.USER_CODE_ERROR
        rec.exception_type = parse_exception_type(out.stderr)
        rec.error_message = f"Process exited with code {out.exit_code}"


@dataclass(frozen=True)
class ExecutionPolicy:
    max_code_bytes: int
    max_timeout_seconds: int
    default_timeout_seconds: int

    @classmethod
    def from_settings(cls, s: Settings) -> "ExecutionPolicy":
        return cls(s.MAX_CODE_BYTES, s.MAX_TIMEOUT_SECONDS, s.DEFAULT_TIMEOUT_SECONDS)


class ExecutionService:
    def __init__(
        self,
        store: ExecutionStore,
        backend: SandboxBackend,
        metrics: Metrics,
        settings: Settings,
        events: EventBus | None = None,
    ) -> None:
        self._events = events
        self._store = store
        self._backend = backend
        self._metrics = metrics
        self._settings = settings
        self._slots = asyncio.Semaphore(settings.MAX_CONCURRENT_SANDBOXES)
        self._tasks: dict[str, asyncio.Task[None]] = {}

    # ---- policy -------------------------------------------------------------

    def check_policy(
        self, code: str, timeout_seconds: int | None, policy: "ExecutionPolicy | None" = None
    ) -> int:
        """Validate against limits; returns the effective timeout."""
        p = policy or ExecutionPolicy.from_settings(self._settings)
        size = len(code.encode("utf-8"))
        if size > p.max_code_bytes:
            raise PolicyViolation(
                "code_too_large", f"Code is {size} bytes; the limit is {p.max_code_bytes}."
            )
        timeout = min(p.default_timeout_seconds, p.max_timeout_seconds)
        if timeout_seconds is not None:
            timeout = timeout_seconds
        if not 1 <= timeout <= p.max_timeout_seconds:
            raise PolicyViolation(
                "timeout_out_of_range",
                f"timeout_seconds must be between 1 and {p.max_timeout_seconds}.",
            )
        return timeout

    # ---- public API -----------------------------------------------------------

    async def submit(
        self,
        code: str,
        timeout_seconds: int | None,
        owner: str,
        policy: ExecutionPolicy | None = None,
    ) -> ExecutionRecord:
        timeout = self.check_policy(code, timeout_seconds, policy)
        rec = ExecutionRecord.new(code, timeout, owner)
        await self._store.create(rec)
        if self._events is not None:
            self._events.open(rec.id)
            self._events.publish(rec.id, "queued", {"execution_id": rec.id})
        log.info(
            "execution queued",
            extra={
                "execution": rec.id,
                "code_size": rec.code_size,
                "code_sha256": rec.code_sha256,
                "timeout_seconds": timeout,
            },
        )
        task = asyncio.create_task(self._run_standalone(rec), name=f"exec-{rec.id}")
        self._tasks[rec.id] = task
        task.add_done_callback(functools.partial(self._forget_task, rec.id))
        return rec

    async def wait(self, execution_id: str, owner: str) -> ExecutionRecord | None:
        rec = await self._store.get(execution_id, owner)
        if rec is None:
            return None
        task = self._tasks.get(execution_id)
        if task is not None:
            try:
                await asyncio.wait_for(
                    asyncio.shield(task), rec.timeout_seconds + WAIT_GRACE_SECONDS
                )
            except TimeoutError:
                pass  # caller gets the current (non-terminal) state
        return await self._store.get(execution_id, owner)

    async def get(self, execution_id: str, owner: str) -> ExecutionRecord | None:
        return await self._store.get(execution_id, owner)

    @asynccontextmanager
    async def open_session(self, lifetime_seconds: int) -> AsyncIterator[SandboxSession]:
        """A sandbox session that holds one concurrency slot for its whole life."""
        async with self._slots, self._backend.session(lifetime_seconds) as session:
            yield session

    async def run_in_session(
        self,
        session: SandboxSession,
        code: str,
        timeout_seconds: int | None,
        owner: str,
        agent_run_id: str,
        policy: ExecutionPolicy | None = None,
    ) -> ExecutionRecord:
        """Synchronous execution inside an existing session (used by the agent).

        Lifecycle events go to the enclosing sink, tagged with execution_id.
        """
        timeout = self.check_policy(code, timeout_seconds, policy)
        rec = ExecutionRecord.new(code, timeout, owner, source="agent", agent_run_id=agent_run_id)
        await self._store.create(rec)
        token = execution_id_var.set(rec.id)
        parent = current_sink()

        def forward(event_type: str, data: dict[str, Any]) -> None:
            if parent is not None:
                parent(event_type, {"execution_id": rec.id, **data})

        try:
            with sink_scope(self._tracking_sink(rec, forward)):
                await self._execute(session, rec)
        except asyncio.CancelledError:
            # e.g. the agent's time budget ran out mid-execution: never leave it "running".
            await self._finish_error(
                rec, ErrorCategory.INTERRUPTED, "Cancelled before the execution finished."
            )
            raise
        finally:
            execution_id_var.reset(token)
        return rec

    async def list_for_agent_run(self, agent_run_id: str, owner: str) -> list[ExecutionRecord]:
        return [r for r in await self._store.list_by_agent_run(agent_run_id) if r.owner == owner]

    async def recover(self) -> int:
        n = await self._store.mark_interrupted()
        if n:
            log.warning("marked stale executions as interrupted", extra={"count": n})
        return n

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # A task cancelled before its first step never reaches its handler.
        await self._store.mark_interrupted()

    # ---- internals ----------------------------------------------------------

    def _forget_task(self, execution_id: str, _task: "asyncio.Task[None]") -> None:
        self._tasks.pop(execution_id, None)

    def _tracking_sink(self, rec: ExecutionRecord, forward: EventSink) -> EventSink:
        """Record phase timings on the execution, then forward the event."""

        def sink(event_type: str, data: dict[str, Any]) -> None:
            if event_type == "sandbox_created":
                rec.create_ms = data.get("create_ms")
            elif event_type == "code_uploaded":
                rec.upload_ms = data.get("upload_ms")
            elif event_type == "exited":
                rec.run_ms = data.get("run_ms")
            elif event_type == "sandbox_killed":
                rec.kill_ms = data.get("kill_ms")
            forward(event_type, data)

        return sink

    def _publish(self, rec: ExecutionRecord, event_type: str, data: dict[str, Any]) -> None:
        if self._events is not None:
            self._events.publish(rec.id, event_type, data)

    async def _run_standalone(self, rec: ExecutionRecord) -> None:
        token = execution_id_var.set(rec.id)
        try:
            lifetime = rec.timeout_seconds + SANDBOX_LIFETIME_GRACE_SECONDS
            sink = self._tracking_sink(rec, lambda t, d: self._publish(rec, t, d))
            with sink_scope(sink):
                async with self.open_session(lifetime) as session:
                    await self._execute(session, rec)
            if rec.kill_ms is not None:
                await self._store.update(rec)  # the kill happens after the result is stored
        except SandboxError as e:  # raised while creating the sandbox
            await self._finish_error(rec, e.category, str(e))
        except asyncio.CancelledError:
            await self._finish_error(
                rec, ErrorCategory.INTERRUPTED, "Server stopped before this execution finished."
            )
            raise
        except Exception:
            log.exception("unexpected error running execution")
            await self._finish_error(rec, ErrorCategory.INTERNAL_ERROR, "Internal error")
        finally:
            execution_id_var.reset(token)
            if self._events is not None:
                out = ExecutionOut.from_record(rec).model_dump(mode="json")
                self._events.publish(rec.id, "finished", {"execution": out})
                self._events.close(rec.id)

    async def _execute(self, session: SandboxSession, rec: ExecutionRecord) -> None:
        """Run and classify. Never raises except on cancellation."""
        rec.status = ExecutionStatus.RUNNING
        rec.started_at = utcnow()
        rec.sandbox_id = session.sandbox_id
        await self._store.update(rec)
        try:
            out = await session.run_python(rec.code, rec.timeout_seconds)
        except SandboxError as e:
            await self._finish_error(rec, e.category, str(e))
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("unexpected error during execution")
            await self._finish_error(rec, ErrorCategory.INTERNAL_ERROR, "Internal error")
            return
        apply_output(rec, out)
        await self._finish(rec)

    async def _finish_error(
        self, rec: ExecutionRecord, category: ErrorCategory, message: str
    ) -> None:
        rec.status = ExecutionStatus.ERROR
        rec.error_category = category
        rec.error_message = message
        await self._finish(rec)

    async def _finish(self, rec: ExecutionRecord) -> None:
        rec.completed_at = utcnow()
        if rec.started_at is not None:
            rec.duration_ms = int((rec.completed_at - rec.started_at).total_seconds() * 1000)
        await self._store.update(rec)
        self._metrics.execution_finished(rec.status, rec.duration_ms or 0)
        log.info(
            "execution finished",
            extra={
                "status": rec.status.value,
                "error_category": rec.error_category.value if rec.error_category else None,
                "exit_code": rec.exit_code,
                "duration_ms": rec.duration_ms,
                "sandbox_id": rec.sandbox_id,
            },
        )
