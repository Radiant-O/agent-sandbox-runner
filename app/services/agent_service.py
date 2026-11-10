"""A bounded tool-calling agent that executes Python through ExecutionService.

The model never runs code itself: every execute_python call goes through the same
policy, concurrency and persistence path as the REST API.
"""

import asyncio
import json
import logging
import uuid
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings
from app.core.metrics import Metrics
from app.domain import ExecutionRecord, ExecutionStatus
from app.llm.base import LLMError, LLMProvider, ToolCall
from app.sandbox.base import SandboxError, SandboxSession
from app.sandbox.events import emit, sink_scope
from app.schemas.agents import AgentRunResult, StopReason
from app.schemas.executions import ExecutionOut
from app.services.events import EventBus
from app.services.execution_service import (
    SANDBOX_LIFETIME_GRACE_SECONDS,
    ExecutionPolicy,
    ExecutionService,
    PolicyViolation,
)

log = logging.getLogger(__name__)

TOOL_NAME = "execute_python"
TOOL_OUTPUT_CHARS = 4000

SYSTEM_PROMPT = """You are a careful assistant that can run Python code.

Decide whether running code is actually needed. If it is, call the execute_python tool.
The code runs in a fresh, isolated sandbox with no internet access; only the Python
standard library is guaranteed. Use print() to show any result you need to see.
Variables persist only within a single call, files persist across calls within this task.

Base your final answer ONLY on tool results you have actually observed. If execution
failed, timed out, or never ran, say so plainly. Never claim code ran successfully
unless a tool result shows status "succeeded"."""

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": (
                "Run a Python 3 script in an isolated sandbox without internet access. "
                "Returns JSON with status (succeeded|failed|timed_out|error), exit_code, "
                "stdout, stderr and exception_type."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Complete Python script."},
                    "timeout_seconds": {
                        "type": "integer",
                        "description": "Optional timeout in seconds.",
                    },
                },
                "required": ["code"],
            },
        },
    }
]


def _error(message: str) -> str:
    return json.dumps({"error": message})


def _result_for_model(rec: ExecutionRecord) -> str:
    return json.dumps(
        {
            "status": rec.status.value,
            "exit_code": rec.exit_code,
            "stdout": rec.stdout[:TOOL_OUTPUT_CHARS],
            "stderr": rec.stderr[:TOOL_OUTPUT_CHARS],
            "output_truncated": rec.stdout_truncated
            or rec.stderr_truncated
            or len(rec.stdout) > TOOL_OUTPUT_CHARS
            or len(rec.stderr) > TOOL_OUTPUT_CHARS,
            "exception_type": rec.exception_type,
            "error_category": rec.error_category.value if rec.error_category else None,
            "error_message": rec.error_message,
            "duration_ms": rec.duration_ms,
        }
    )


@dataclass(frozen=True)
class AgentLimits:
    max_steps: int
    max_tool_calls: int
    timeout_seconds: float
    max_tokens: int

    @classmethod
    def from_settings(cls, s: Settings) -> "AgentLimits":
        return cls(
            s.AGENT_MAX_STEPS, s.AGENT_MAX_TOOL_CALLS, s.AGENT_TIMEOUT_SECONDS, s.AGENT_MAX_TOKENS
        )


@dataclass
class _RunState:
    run_id: str
    owner: str
    stack: AsyncExitStack
    limits: AgentLimits
    policy: ExecutionPolicy | None
    session: SandboxSession | None = None
    steps: int = 0
    tool_calls: int = 0
    messages: list[dict[str, Any]] = field(default_factory=list)


class AgentService:
    def __init__(
        self,
        llm: LLMProvider,
        executions: ExecutionService,
        metrics: Metrics,
        settings: Settings,
        events: EventBus | None = None,
    ) -> None:
        self._llm = llm
        self._executions = executions
        self._metrics = metrics
        self._settings = settings
        self._events = events
        self._tasks: set[asyncio.Task[None]] = set()

    # ---- streaming entry point --------------------------------------------------

    def start(
        self,
        task: str,
        owner: str,
        limits: AgentLimits | None = None,
        policy: ExecutionPolicy | None = None,
    ) -> str:
        """Start a run in the background; its events stream on the bus under the run id."""
        if self._events is None:
            raise RuntimeError("AgentService.start requires an EventBus")
        bus = self._events
        run_id = "run_" + uuid.uuid4().hex
        bus.open(run_id)
        bus.publish(run_id, "started", {"run_id": run_id, "task": task})

        async def runner() -> None:
            result: AgentRunResult | None = None
            try:
                with sink_scope(lambda t, d: bus.publish(run_id, t, d)):
                    result = await self.run(
                        task, owner, run_id=run_id, limits=limits, policy=policy
                    )
            except Exception:
                log.exception("agent run crashed", extra={"agent_run_id": run_id})
            finally:
                if result is not None:
                    bus.publish(run_id, "finished", {"run": result.model_dump(mode="json")})
                else:
                    bus.publish(run_id, "failed", {"message": "Agent run failed unexpectedly."})
                bus.close(run_id)

        t = asyncio.create_task(runner(), name=f"agent-{run_id}")
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)
        return run_id

    async def shutdown(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    # ---- core loop ----------------------------------------------------------------

    async def run(
        self,
        task: str,
        owner: str,
        *,
        run_id: str | None = None,
        limits: AgentLimits | None = None,
        policy: ExecutionPolicy | None = None,
    ) -> AgentRunResult:
        run_id = run_id or "run_" + uuid.uuid4().hex
        lim = limits or AgentLimits.from_settings(self._settings)
        answer: str | None = None
        async with AsyncExitStack() as stack:  # closes the sandbox session, even on timeout
            st = _RunState(run_id=run_id, owner=owner, stack=stack, limits=lim, policy=policy)
            st.messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": task},
            ]
            stop_reason: StopReason
            try:
                async with asyncio.timeout(lim.timeout_seconds):
                    stop_reason, answer = await self._loop(st)
            except TimeoutError:
                stop_reason, answer = "time_limit", None

        records = await self._executions.list_for_agent_run(run_id, owner)
        self._metrics.agent_run_finished(stop_reason)
        log.info(
            "agent run finished",
            extra={
                "agent_run_id": run_id,
                "stop_reason": stop_reason,
                "steps": st.steps,
                "tool_calls": st.tool_calls,
                "executions": len(records),
            },
        )
        return AgentRunResult(
            id=run_id,
            stop_reason=stop_reason,
            answer=answer if stop_reason == "completed" else None,
            executions=[ExecutionOut.from_record(r) for r in records],
            any_execution_succeeded=any(r.status is ExecutionStatus.SUCCEEDED for r in records),
            steps=st.steps,
            tool_calls=st.tool_calls,
        )

    async def _loop(self, st: _RunState) -> tuple[StopReason, str | None]:
        lim = st.limits
        while True:
            if st.steps >= lim.max_steps:
                return "step_limit", None
            st.steps += 1
            emit("step_started", step=st.steps)
            try:
                turn = await self._llm.complete(st.messages, TOOLS, lim.max_tokens)
            except LLMError as e:
                log.warning("llm call failed", extra={"agent_run_id": st.run_id, "error": str(e)})
                return "llm_error", None

            if turn.text:
                emit("model_text", step=st.steps, text=turn.text, final=not turn.tool_calls)
            if not turn.tool_calls:
                return "completed", turn.text or ""

            st.messages.append(
                {
                    "role": "assistant",
                    "content": turn.text,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": tc.arguments},
                        }
                        for tc in turn.tool_calls
                    ],
                }
            )
            for tc in turn.tool_calls:
                if st.tool_calls >= lim.max_tool_calls:
                    return "tool_call_limit", None
                st.tool_calls += 1
                content = await self._handle_tool_call(st, tc)
                st.messages.append({"role": "tool", "tool_call_id": tc.id, "content": content})
                emit("tool_result", call_id=tc.id, **json.loads(content))

    async def _handle_tool_call(self, st: _RunState, tc: ToolCall) -> str:
        if tc.name != TOOL_NAME:
            return _error(f"Unknown tool '{tc.name}'. The only tool is {TOOL_NAME}.")
        try:
            args = json.loads(tc.arguments or "{}")
        except json.JSONDecodeError:
            return _error("Tool arguments were not valid JSON.")
        if not isinstance(args, dict):
            return _error("Tool arguments must be a JSON object.")
        code = args.get("code")
        if not isinstance(code, str) or not code.strip():
            return _error("'code' is required and must be a non-empty string.")
        timeout = args.get("timeout_seconds")
        if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, int)):
            return _error("'timeout_seconds' must be an integer.")
        emit("tool_call", call_id=tc.id, code=code, timeout_seconds=timeout)

        if st.session is None:
            lifetime = int(st.limits.timeout_seconds) + SANDBOX_LIFETIME_GRACE_SECONDS
            try:
                st.session = await st.stack.enter_async_context(
                    self._executions.open_session(lifetime)
                )
            except SandboxError as e:
                return _error(f"Sandbox unavailable ({e.category.value}): {e}")

        try:
            rec = await self._executions.run_in_session(
                st.session, code, timeout, st.owner, agent_run_id=st.run_id, policy=st.policy
            )
        except PolicyViolation as e:
            return _error(e.message)
        return _result_for_model(rec)
