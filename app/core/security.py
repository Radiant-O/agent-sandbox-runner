"""API key identity and per-key rate limiting."""

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass


def owner_id(api_key: str) -> str:
    """Stable, non-reversible identifier for an API key (used to scope executions)."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


@dataclass
class _Bucket:
    tokens: float
    updated: float


class RateLimiter:
    """Token bucket per key. In-memory: limits are per process, not per cluster."""

    def __init__(self, per_minute: int, clock: Callable[[], float] = time.monotonic) -> None:
        self._capacity = float(per_minute)
        self._rate = per_minute / 60.0  # tokens per second
        self._clock = clock
        self._buckets: dict[str, _Bucket] = {}

    def check(self, key: str) -> float | None:
        """Consume a token. Returns None if allowed, else seconds until a token is available."""
        now = self._clock()
        b = self._buckets.get(key)
        if b is None:
            b = self._buckets[key] = _Bucket(self._capacity, now)
        b.tokens = min(self._capacity, b.tokens + (now - b.updated) * self._rate)
        b.updated = now
        if b.tokens >= 1:
            b.tokens -= 1
            return None
        return (1 - b.tokens) / self._rate
