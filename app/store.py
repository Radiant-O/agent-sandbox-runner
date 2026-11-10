"""SQLite persistence for execution records."""

import dataclasses
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from app.domain import ErrorCategory, ExecutionRecord, ExecutionStatus, utcnow

_FIELDS = [f.name for f in dataclasses.fields(ExecutionRecord)]
_DATETIME_FIELDS = {"created_at", "started_at", "completed_at"}
_BOOL_FIELDS = {"stdout_truncated", "stderr_truncated"}

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS executions (
    {", ".join(f + (" TEXT PRIMARY KEY" if f == "id" else "") for f in _FIELDS)}
);
CREATE INDEX IF NOT EXISTS ix_executions_owner ON executions(owner);
CREATE INDEX IF NOT EXISTS ix_executions_agent_run ON executions(agent_run_id);
CREATE INDEX IF NOT EXISTS ix_executions_status ON executions(status);
"""


def _to_row(rec: ExecutionRecord) -> list[Any]:
    row: list[Any] = []
    for name in _FIELDS:
        v = getattr(rec, name)
        if isinstance(v, datetime):
            v = v.isoformat()
        elif name in _BOOL_FIELDS:
            v = int(v)
        elif isinstance(v, ExecutionStatus | ErrorCategory):
            v = v.value
        row.append(v)
    return row


def _from_row(row: aiosqlite.Row) -> ExecutionRecord:
    data = dict(zip(_FIELDS, row, strict=True))
    for name in _DATETIME_FIELDS:
        if data[name] is not None:
            data[name] = datetime.fromisoformat(data[name])
    for name in _BOOL_FIELDS:
        data[name] = bool(data[name])
    data["status"] = ExecutionStatus(data["status"])
    if data["error_category"] is not None:
        data["error_category"] = ErrorCategory(data["error_category"])
    return ExecutionRecord(**data)


class ExecutionStore:
    def __init__(self, path: str) -> None:
        self._path = path
        self._db: aiosqlite.Connection | None = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("ExecutionStore.init() was not called")
        return self._db

    async def init(self) -> None:
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript(_SCHEMA)
        # Lightweight forward migration: add columns introduced after a DB was created.
        async with self._db.execute("PRAGMA table_info(executions)") as cur:
            existing = {row[1] for row in await cur.fetchall()}
        for name in _FIELDS:
            if name not in existing:
                await self._db.execute(f"ALTER TABLE executions ADD COLUMN {name}")
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def create(self, rec: ExecutionRecord) -> None:
        placeholders = ", ".join("?" for _ in _FIELDS)
        await self.db.execute(
            f"INSERT INTO executions ({', '.join(_FIELDS)}) VALUES ({placeholders})",  # noqa: S608
            _to_row(rec),
        )
        await self.db.commit()

    async def update(self, rec: ExecutionRecord) -> None:
        cols = [f for f in _FIELDS if f != "id"]
        assignments = ", ".join(f"{c} = ?" for c in cols)
        values = _to_row(rec)
        id_index = _FIELDS.index("id")
        params = [v for i, v in enumerate(values) if i != id_index] + [rec.id]
        await self.db.execute(
            f"UPDATE executions SET {assignments} WHERE id = ?",  # noqa: S608
            params,
        )
        await self.db.commit()

    async def get(self, execution_id: str, owner: str) -> ExecutionRecord | None:
        async with self.db.execute(
            f"SELECT {', '.join(_FIELDS)} FROM executions WHERE id = ? AND owner = ?",  # noqa: S608
            (execution_id, owner),
        ) as cur:
            row = await cur.fetchone()
        return _from_row(row) if row else None

    async def list_by_agent_run(self, agent_run_id: str) -> list[ExecutionRecord]:
        async with self.db.execute(
            f"SELECT {', '.join(_FIELDS)} FROM executions "  # noqa: S608
            "WHERE agent_run_id = ? ORDER BY created_at",
            (agent_run_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [_from_row(r) for r in rows]

    async def mark_interrupted(self) -> int:
        cur = await self.db.execute(
            "UPDATE executions SET status = ?, error_category = ?, error_message = ?, "
            "completed_at = ? WHERE status IN (?, ?)",
            (
                ExecutionStatus.ERROR.value,
                ErrorCategory.INTERRUPTED.value,
                "Server stopped before this execution finished.",
                utcnow().isoformat(),
                ExecutionStatus.QUEUED.value,
                ExecutionStatus.RUNNING.value,
            ),
        )
        await self.db.commit()
        return cur.rowcount
