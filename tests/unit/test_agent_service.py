import json
from collections.abc import AsyncIterator

import pytest

from app.core.config import Settings
from app.core.metrics import Metrics
from app.llm.base import LLMError, LLMTurn, ToolCall
from app.sandbox.base import RunOutput
from app.services.agent_service import AgentService
from app.services.execution_service import ExecutionService
from app.store import ExecutionStore
from tests.fakes import FakeSandboxBackend, ScriptedLLM


def call(code: str = "print(1)", cid: str = "c1", raw: str | None = None) -> LLMTurn:
    args = raw if raw is not None else json.dumps({"code": code})
    return LLMTurn(text=None, tool_calls=[ToolCall(cid, "execute_python", args)])


def say(text: str) -> LLMTurn:
    return LLMTurn(text=text)


def fail_out() -> RunOutput:
    return RunOutput("", "ZeroDivisionError: division by zero", False, False, 1, False, 3)


@pytest.fixture
async def store(settings: Settings) -> AsyncIterator[ExecutionStore]:
    s = ExecutionStore(settings.DATABASE_PATH)
    await s.init()
    yield s
    await s.close()


def build(
    settings: Settings,
    store: ExecutionStore,
    llm: ScriptedLLM,
    backend: FakeSandboxBackend | None = None,
) -> tuple[AgentService, FakeSandboxBackend, Metrics]:
    backend = backend or FakeSandboxBackend()
    metrics = Metrics()
    execs = ExecutionService(store, backend, metrics, settings)
    return AgentService(llm, execs, metrics, settings), backend, metrics


def tool_messages(msgs: list[dict[str, object]]) -> list[dict[str, object]]:
    return [m for m in msgs if m["role"] == "tool"]


async def test_answer_without_tool_use(settings: Settings, store: ExecutionStore) -> None:
    agent, backend, metrics = build(settings, store, ScriptedLLM([say("Paris.")]))
    res = await agent.run("Capital of France?", "o")
    assert res.stop_reason == "completed"
    assert res.answer == "Paris."
    assert res.executions == [] and res.tool_calls == 0 and res.steps == 1
    assert backend.created == 0
    assert metrics.snapshot()["agent_runs_by_stop_reason"] == {"completed": 1}


async def test_tool_call_then_answer(settings: Settings, store: ExecutionStore) -> None:
    ok = RunOutput("6765\n", "", False, False, 0, False, 3)
    llm = ScriptedLLM([call("print(fib(20))"), say("It is 6765.")])
    agent, _, _ = build(settings, store, llm, FakeSandboxBackend([ok]))
    res = await agent.run("20th fibonacci?", "o")
    assert res.stop_reason == "completed"
    assert res.answer == "It is 6765."
    assert len(res.executions) == 1
    assert res.executions[0].status == "succeeded"
    assert res.executions[0].agent_run_id == res.id
    assert res.any_execution_succeeded is True
    tool_msgs = tool_messages(llm.requests[1])
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["tool_call_id"] == "c1"
    payload = json.loads(str(tool_msgs[0]["content"]))
    assert payload["status"] == "succeeded" and payload["stdout"] == "6765\n"
    # assistant tool-call message precedes the tool result
    assistant = [m for m in llm.requests[1] if m["role"] == "assistant"]
    assert assistant and assistant[-1]["tool_calls"][0]["id"] == "c1"  # type: ignore[index]


async def test_invalid_tool_args_fed_back_as_error(
    settings: Settings, store: ExecutionStore
) -> None:
    llm = ScriptedLLM([call(raw="not json"), say("Sorry, I could not run it.")])
    agent, backend, _ = build(settings, store, llm)
    res = await agent.run("x", "o")
    assert res.stop_reason == "completed"
    assert res.executions == []
    assert res.tool_calls == 1
    assert "error" in json.loads(str(tool_messages(llm.requests[1])[0]["content"]))
    assert backend.created == 0


async def test_unknown_tool_and_missing_code_are_errors(
    settings: Settings, store: ExecutionStore
) -> None:
    llm = ScriptedLLM(
        [
            LLMTurn(text=None, tool_calls=[ToolCall("a", "rm_rf", "{}")]),
            call(raw='{"timeout_seconds": 3}', cid="b"),
            say("done"),
        ]
    )
    agent, _, _ = build(settings, store, llm)
    res = await agent.run("x", "o")
    msgs = tool_messages(llm.requests[2])
    assert all("error" in json.loads(str(m["content"])) for m in msgs)
    assert res.executions == []


async def test_policy_violation_fed_back(settings: Settings, store: ExecutionStore) -> None:
    settings.MAX_CODE_BYTES = 3
    llm = ScriptedLLM([call("print(12345)"), say("too big")])
    agent, _, _ = build(settings, store, llm)
    res = await agent.run("x", "o")
    content = json.loads(str(tool_messages(llm.requests[1])[0]["content"]))
    assert "bytes" in content["error"]
    assert res.executions == []


async def test_tool_call_limit_stops_loop(settings: Settings, store: ExecutionStore) -> None:
    settings.AGENT_MAX_TOOL_CALLS = 2
    settings.AGENT_MAX_STEPS = 10
    llm = ScriptedLLM([call()], repeat_last=True)
    agent, _, _ = build(settings, store, llm)
    res = await agent.run("loop forever", "o")
    assert res.stop_reason == "tool_call_limit"
    assert res.answer is None
    assert len(res.executions) == 2
    assert res.tool_calls == 2


async def test_step_limit(settings: Settings, store: ExecutionStore) -> None:
    settings.AGENT_MAX_STEPS = 2
    settings.AGENT_MAX_TOOL_CALLS = 10
    llm = ScriptedLLM([call()], repeat_last=True)
    agent, _, _ = build(settings, store, llm)
    res = await agent.run("x", "o")
    assert res.stop_reason == "step_limit"
    assert res.answer is None
    assert res.steps == 2


async def test_time_limit(settings: Settings, store: ExecutionStore) -> None:
    settings.AGENT_TIMEOUT_SECONDS = 0.2
    llm = ScriptedLLM([call()], repeat_last=True)
    agent, backend, _ = build(settings, store, llm, FakeSandboxBackend(delay=1))
    res = await agent.run("x", "o")
    assert res.stop_reason == "time_limit"
    assert res.answer is None
    assert backend.killed == backend.created  # session closed even on timeout
    # the in-flight execution is recorded as interrupted, never left "running"
    assert [e.error_category for e in res.executions] == ["interrupted"]


async def test_llm_error_keeps_executions(settings: Settings, store: ExecutionStore) -> None:
    llm = ScriptedLLM([call(), LLMError("HTTP 502")])
    agent, _, _ = build(settings, store, llm)
    res = await agent.run("x", "o")
    assert res.stop_reason == "llm_error"
    assert res.answer is None
    assert len(res.executions) == 1


async def test_sandbox_reused_within_run_and_killed(
    settings: Settings, store: ExecutionStore
) -> None:
    llm = ScriptedLLM([call(cid="a"), call(cid="b"), say("done")])
    agent, backend, _ = build(settings, store, llm)
    res = await agent.run("x", "o")
    assert len(res.executions) == 2
    assert backend.created == 1
    assert backend.killed == 1
    assert backend.lifetimes == [int(settings.AGENT_TIMEOUT_SECONDS) + 60]


async def test_failed_execution_visible_to_model(settings: Settings, store: ExecutionStore) -> None:
    llm = ScriptedLLM([call("1/0"), say("It failed with ZeroDivisionError.")])
    agent, _, _ = build(settings, store, llm, FakeSandboxBackend([fail_out()]))
    res = await agent.run("x", "o")
    assert res.any_execution_succeeded is False
    assert res.executions[0].status == "failed"
    content = json.loads(str(tool_messages(llm.requests[1])[0]["content"]))
    assert content["status"] == "failed"
    assert content["exception_type"] == "ZeroDivisionError"


async def test_tool_output_trimmed_for_model(settings: Settings, store: ExecutionStore) -> None:
    big = RunOutput("x" * 10_000, "", False, False, 0, False, 3)
    llm = ScriptedLLM([call(), say("ok")])
    agent, _, _ = build(settings, store, llm, FakeSandboxBackend([big]))
    await agent.run("x", "o")
    content = json.loads(str(tool_messages(llm.requests[1])[0]["content"]))
    assert len(content["stdout"]) <= 4100
