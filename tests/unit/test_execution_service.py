from collections.abc import AsyncIterator

import pytest

from app.core.config import Settings
from app.core.metrics import Metrics
from app.domain import ErrorCategory, ExecutionRecord, ExecutionStatus
from app.sandbox.base import RunOutput, SandboxUnavailableError, SandboxUpstreamError
from app.services.execution_service import (
    ExecutionService,
    PolicyViolation,
    parse_exception_type,
)
from app.store import ExecutionStore
from tests.fakes import FakeSandboxBackend


def out(
    exit_code: int | None = 0,
    stdout: str = "",
    stderr: str = "",
    timed_out: bool = False,
) -> RunOutput:
    return RunOutput(stdout, stderr, False, False, exit_code, timed_out, 5)


@pytest.fixture
async def store(settings: Settings) -> AsyncIterator[ExecutionStore]:
    s = ExecutionStore(settings.DATABASE_PATH)
    await s.init()
    yield s
    await s.close()


def make(
    settings: Settings, store: ExecutionStore, backend: FakeSandboxBackend
) -> tuple[ExecutionService, Metrics]:
    m = Metrics()
    return ExecutionService(store, backend, m, settings), m


async def test_submit_then_wait_succeeds(settings: Settings, store: ExecutionStore) -> None:
    backend = FakeSandboxBackend([out(0, stdout="4\n")])
    svc, metrics = make(settings, store, backend)
    rec = await svc.submit("print(2+2)", None, owner="o")
    assert rec.status is ExecutionStatus.QUEUED
    done = await svc.wait(rec.id, "o")
    assert done.status is ExecutionStatus.SUCCEEDED
    assert done.stdout == "4\n"
    assert done.exit_code == 0
    assert done.sandbox_id is not None and done.sandbox_id.startswith("fake-sbx-")
    assert done.duration_ms is not None and done.duration_ms >= 0
    assert done.started_at is not None and done.completed_at is not None
    assert done.error_category is None
    assert backend.lifetimes == [settings.DEFAULT_TIMEOUT_SECONDS + 60]
    assert metrics.snapshot()["executions_by_status"] == {"succeeded": 1}


async def test_nonzero_exit_is_failed_user_code_error_with_exception_type(
    settings: Settings, store: ExecutionStore
) -> None:
    tb = 'Traceback (most recent call last):\n  File "main.py", line 1\nValueError: bad\n'
    svc, _ = make(settings, store, FakeSandboxBackend([out(1, stderr=tb)]))
    done = await svc.wait((await svc.submit("raise ValueError('bad')", None, "o")).id, "o")
    assert done.status is ExecutionStatus.FAILED
    assert done.error_category is ErrorCategory.USER_CODE_ERROR
    assert done.exception_type == "ValueError"
    assert done.exit_code == 1


async def test_timeout_maps_to_timed_out(settings: Settings, store: ExecutionStore) -> None:
    svc, _ = make(settings, store, FakeSandboxBackend([out(None, "part", timed_out=True)]))
    done = await svc.wait((await svc.submit("while True: pass", 2, "o")).id, "o")
    assert done.status is ExecutionStatus.TIMED_OUT
    assert done.error_category is ErrorCategory.TIMEOUT
    assert done.stdout == "part"


async def test_create_failure_maps_to_error_sandbox_unavailable(
    settings: Settings, store: ExecutionStore
) -> None:
    backend = FakeSandboxBackend(create_error=SandboxUnavailableError("no capacity"))
    svc, _ = make(settings, store, backend)
    done = await svc.wait((await svc.submit("print(1)", None, "o")).id, "o")
    assert done.status is ExecutionStatus.ERROR
    assert done.error_category is ErrorCategory.SANDBOX_UNAVAILABLE
    assert done.error_message == "no capacity"


async def test_upstream_error_mid_run(settings: Settings, store: ExecutionStore) -> None:
    svc, _ = make(settings, store, FakeSandboxBackend([SandboxUpstreamError("gone")]))
    done = await svc.wait((await svc.submit("print(1)", None, "o")).id, "o")
    assert done.status is ExecutionStatus.ERROR
    assert done.error_category is ErrorCategory.UPSTREAM_ERROR


async def test_unexpected_exception_is_internal_error(
    settings: Settings, store: ExecutionStore
) -> None:
    svc, _ = make(settings, store, FakeSandboxBackend([RuntimeError("bug")]))
    done = await svc.wait((await svc.submit("print(1)", None, "o")).id, "o")
    assert done.status is ExecutionStatus.ERROR
    assert done.error_category is ErrorCategory.INTERNAL_ERROR


async def test_code_too_large_raises_policy_violation(
    settings: Settings, store: ExecutionStore
) -> None:
    settings.MAX_CODE_BYTES = 10
    svc, _ = make(settings, store, FakeSandboxBackend())
    with pytest.raises(PolicyViolation) as ei:
        await svc.submit("x = 'é' * 100", None, "o")
    assert ei.value.code == "code_too_large"


@pytest.mark.parametrize("bad_timeout", [0, 121])
async def test_timeout_out_of_range_raises_policy_violation(
    settings: Settings, store: ExecutionStore, bad_timeout: int
) -> None:
    svc, _ = make(settings, store, FakeSandboxBackend())
    with pytest.raises(PolicyViolation) as ei:
        await svc.submit("print(1)", bad_timeout, "o")
    assert ei.value.code == "timeout_out_of_range"


async def test_default_timeout_applied(settings: Settings, store: ExecutionStore) -> None:
    svc, _ = make(settings, store, FakeSandboxBackend())
    rec = await svc.submit("print(1)", None, "o")
    assert rec.timeout_seconds == 30
    await svc.wait(rec.id, "o")


async def test_concurrency_cap_is_respected(settings: Settings, store: ExecutionStore) -> None:
    settings.MAX_CONCURRENT_SANDBOXES = 2
    backend = FakeSandboxBackend(delay=0.2)
    svc, _ = make(settings, store, backend)
    recs = [await svc.submit(f"print({i})", None, "o") for i in range(6)]
    done = [await svc.wait(r.id, "o") for r in recs]
    assert backend.max_live <= 2
    assert all(d.status is ExecutionStatus.SUCCEEDED for d in done)


async def test_recover_marks_interrupted(settings: Settings, store: ExecutionStore) -> None:
    stale = ExecutionRecord.new("print(1)", 30, owner="o")
    stale.status = ExecutionStatus.RUNNING
    await store.create(stale)
    svc, _ = make(settings, store, FakeSandboxBackend())
    assert await svc.recover() == 1
    got = await svc.get(stale.id, "o")
    assert got is not None and got.error_category is ErrorCategory.INTERRUPTED


async def test_shutdown_interrupts_inflight(settings: Settings, store: ExecutionStore) -> None:
    svc, _ = make(settings, store, FakeSandboxBackend(delay=5))
    rec = await svc.submit("print(1)", None, "o")
    await svc.shutdown()
    got = await svc.get(rec.id, "o")
    assert got is not None
    assert got.status is ExecutionStatus.ERROR
    assert got.error_category is ErrorCategory.INTERRUPTED


async def test_run_in_session_persists_agent_record(
    settings: Settings, store: ExecutionStore
) -> None:
    svc, _ = make(settings, store, FakeSandboxBackend([out(0, "hi\n")]))
    async with svc.open_session(240) as session:
        rec = await svc.run_in_session(session, "print('hi')", None, "o", agent_run_id="run_1")
    assert rec.status is ExecutionStatus.SUCCEEDED
    assert rec.source == "agent"
    stored = await store.list_by_agent_run("run_1")
    assert [r.id for r in stored] == [rec.id]


def test_parse_exception_type() -> None:
    assert parse_exception_type("Traceback...\nValueError: bad\n") == "ValueError"
    assert parse_exception_type("  File x\nSyntaxError: invalid syntax") == "SyntaxError"
    assert parse_exception_type("json.decoder.JSONDecodeError: x") == "json.decoder.JSONDecodeError"
    assert parse_exception_type("KeyboardInterrupt") == "KeyboardInterrupt"
    assert parse_exception_type("hello") is None
    assert parse_exception_type("") is None


# ---- live lifecycle events (console UI) ----------------------------------------


async def test_standalone_execution_publishes_lifecycle_in_order(
    settings: Settings, store: ExecutionStore
) -> None:
    from app.services.events import EventBus

    bus = EventBus()
    backend = FakeSandboxBackend([out(0, stdout="4\n")])
    svc = ExecutionService(store, backend, Metrics(), settings, events=bus)
    rec = await svc.submit("print(2+2)", None, "o")
    await svc.wait(rec.id, "o")
    events = [e async for e in bus.subscribe(rec.id)]
    assert [e["type"] for e in events] == [
        "queued",
        "sandbox_creating",
        "sandbox_created",
        "code_uploaded",
        "stdout",
        "exited",
        "sandbox_killed",
        "finished",
    ]
    finished = events[-1]["data"]["execution"]
    assert finished["status"] == "succeeded"
    assert finished["create_ms"] is not None and finished["kill_ms"] is not None
    stored = await store.get(rec.id, "o")
    assert stored is not None
    assert None not in (stored.create_ms, stored.upload_ms, stored.run_ms, stored.kill_ms)


async def test_create_failure_still_finishes_stream(
    settings: Settings, store: ExecutionStore
) -> None:
    from app.services.events import EventBus

    bus = EventBus()
    backend = FakeSandboxBackend(create_error=SandboxUnavailableError("no capacity"))
    svc = ExecutionService(store, backend, Metrics(), settings, events=bus)
    rec = await svc.submit("print(1)", None, "o")
    await svc.wait(rec.id, "o")
    types = [e["type"] async for e in bus.subscribe(rec.id)]
    assert types[0] == "queued" and types[-1] == "finished"
    assert "sandbox_created" not in types
