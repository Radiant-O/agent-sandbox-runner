from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.domain import ErrorCategory, ExecutionRecord, ExecutionStatus, utcnow
from app.store import ExecutionStore


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[ExecutionStore]:
    s = ExecutionStore(str(tmp_path / "sub" / "x.db"))
    await s.init()
    yield s
    await s.close()


async def test_create_then_get_roundtrip(store: ExecutionStore) -> None:
    rec = ExecutionRecord.new("print(1)", 30, owner="o1", source="agent", agent_run_id="run_1")
    await store.create(rec)
    got = await store.get(rec.id, "o1")
    assert got == rec


async def test_get_wrong_owner_returns_none(store: ExecutionStore) -> None:
    rec = ExecutionRecord.new("print(1)", 30, owner="o1")
    await store.create(rec)
    assert await store.get(rec.id, "o2") is None


async def test_update_persists_status_and_output(store: ExecutionStore) -> None:
    rec = ExecutionRecord.new("1/0", 30, owner="o1")
    await store.create(rec)
    rec.status = ExecutionStatus.FAILED
    rec.error_category = ErrorCategory.USER_CODE_ERROR
    rec.stderr = "ZeroDivisionError: division by zero"
    rec.stderr_truncated = True
    rec.exit_code = 1
    rec.started_at = rec.completed_at = utcnow()
    rec.duration_ms = 12
    rec.sandbox_id = "sbx-1"
    await store.update(rec)
    assert await store.get(rec.id, "o1") == rec


async def test_list_by_agent_run(store: ExecutionStore) -> None:
    a = ExecutionRecord.new("1", 30, owner="o", source="agent", agent_run_id="run_x")
    b = ExecutionRecord.new("2", 30, owner="o")
    await store.create(a)
    await store.create(b)
    assert [r.id for r in await store.list_by_agent_run("run_x")] == [a.id]


async def test_mark_interrupted_only_touches_active(store: ExecutionStore) -> None:
    queued = ExecutionRecord.new("1", 30, owner="o")
    running = ExecutionRecord.new("2", 30, owner="o")
    running.status = ExecutionStatus.RUNNING
    done = ExecutionRecord.new("3", 30, owner="o")
    done.status = ExecutionStatus.SUCCEEDED
    for r in (queued, running, done):
        await store.create(r)
    assert await store.mark_interrupted() == 2
    q = await store.get(queued.id, "o")
    assert q is not None
    assert q.status is ExecutionStatus.ERROR
    assert q.error_category is ErrorCategory.INTERRUPTED
    assert q.completed_at is not None
    assert await store.get(done.id, "o") == done
