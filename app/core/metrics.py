"""In-process metrics. Exposed as JSON at GET /metrics.

Deliberately dependency-free; single-instance only (documented in SECURITY.md/README).
"""

import math
from collections import Counter, deque
from typing import Any

from app.domain import ExecutionStatus


def _percentile(sorted_values: list[int], p: float) -> int | None:
    """Nearest-rank percentile."""
    if not sorted_values:
        return None
    rank = max(1, math.ceil(p * len(sorted_values)))
    return sorted_values[rank - 1]


class Metrics:
    def __init__(self, window: int = 1000) -> None:
        self._by_status: Counter[str] = Counter()
        self._durations: deque[int] = deque(maxlen=window)
        self._created = 0
        self._killed = 0
        self._cleanup_failures = 0
        self._create_retries = 0
        self._create_ms_total = 0
        self._agent_runs: Counter[str] = Counter()

    def execution_finished(self, status: ExecutionStatus, duration_ms: int) -> None:
        self._by_status[status.value] += 1
        self._durations.append(duration_ms)

    def sandbox_created(self, create_ms: int) -> None:
        self._created += 1
        self._create_ms_total += create_ms

    def sandbox_killed(self) -> None:
        self._killed += 1

    def cleanup_failed(self) -> None:
        self._cleanup_failures += 1

    def create_retried(self) -> None:
        self._create_retries += 1

    def agent_run_finished(self, stop_reason: str) -> None:
        self._agent_runs[stop_reason] += 1

    def snapshot(self) -> dict[str, Any]:
        durations = sorted(self._durations)
        return {
            "executions_by_status": dict(self._by_status),
            "execution_duration_ms_p50": _percentile(durations, 0.50),
            "execution_duration_ms_p95": _percentile(durations, 0.95),
            # A failed kill still counts as "not live" from our side: the sandbox
            # lifetime timeout destroys it on E2B's side.
            "sandboxes_live": self._created - self._killed - self._cleanup_failures,
            "sandboxes_created_total": self._created,
            "sandbox_create_ms_avg": (
                round(self._create_ms_total / self._created) if self._created else None
            ),
            "cleanup_failures_total": self._cleanup_failures,
            "create_retries_total": self._create_retries,
            "agent_runs_by_stop_reason": dict(self._agent_runs),
        }
