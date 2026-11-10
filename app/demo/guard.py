"""Spend protection for the public demo: per-visitor windows and a persistent daily budget."""

import hashlib
import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import aiosqlite


def visitor_id(ip: str) -> str:
    """Non-reversible visitor key (we never store raw IPs)."""
    return hashlib.sha256(f"demo-visitor:{ip}".encode()).hexdigest()[:16]


class VisitorLimiter:
    """Sliding one-hour window per (visitor, kind). In-memory: per process."""

    WINDOW_SECONDS = 3600.0

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def check(self, visitor: str, kind: str, limit: int) -> float | None:
        """Record a hit if allowed. Returns None if allowed, else seconds to wait."""
        now = self._clock()
        hits = self._hits[(visitor, kind)]
        while hits and now - hits[0] >= self.WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= limit:
            return self.WINDOW_SECONDS - (now - hits[0])
        hits.append(now)
        return None


_BUDGET_SCHEMA = """
CREATE TABLE IF NOT EXISTS demo_budget (
    day TEXT NOT NULL,
    kind TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, kind)
);
"""


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def next_reset_iso() -> str:
    tomorrow = datetime.now(UTC).date() + timedelta(days=1)
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=UTC).isoformat()


class DailyBudget:
    """Global per-UTC-day spend caps, persisted so restarts don't reset them."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def init(self) -> None:
        await self._db.executescript(_BUDGET_SCHEMA)
        await self._db.commit()

    async def try_consume(self, kind: str, cap: int) -> bool:
        day = _today()
        await self._db.execute(
            "INSERT OR IGNORE INTO demo_budget (day, kind, used) VALUES (?, ?, 0)", (day, kind)
        )
        cur = await self._db.execute(
            "UPDATE demo_budget SET used = used + 1 WHERE day = ? AND kind = ? AND used < ?",
            (day, kind, cap),
        )
        await self._db.commit()
        return cur.rowcount == 1

    async def used(self, kind: str) -> int:
        async with self._db.execute(
            "SELECT used FROM demo_budget WHERE day = ? AND kind = ?", (_today(), kind)
        ) as cur:
            row = await cur.fetchone()
        return int(row[0]) if row else 0
