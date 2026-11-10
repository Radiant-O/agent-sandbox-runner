"""Core domain types for executions."""

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal


class ExecutionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"  # exit code 0
    FAILED = "failed"  # user code exited non-zero (syntax/runtime error)
    TIMED_OUT = "timed_out"  # user code exceeded its timeout
    ERROR = "error"  # infrastructure problem, not the user's fault

    @property
    def is_terminal(self) -> bool:
        return self not in (ExecutionStatus.QUEUED, ExecutionStatus.RUNNING)


class ErrorCategory(StrEnum):
    USER_CODE_ERROR = "user_code_error"
    TIMEOUT = "timeout"
    SANDBOX_UNAVAILABLE = "sandbox_unavailable"
    UPSTREAM_ERROR = "upstream_error"
    AUTH_ERROR = "auth_error"
    INTERRUPTED = "interrupted"
    INTERNAL_ERROR = "internal_error"


Source = Literal["api", "agent"]


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class ExecutionRecord:
    id: str
    owner: str
    status: ExecutionStatus
    code: str
    code_sha256: str
    code_size: int
    timeout_seconds: int
    source: Source
    agent_run_id: str | None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    stdout: str = ""
    stderr: str = ""
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    exit_code: int | None = None
    error_category: ErrorCategory | None = None
    error_message: str | None = None
    exception_type: str | None = None
    sandbox_id: str | None = field(default=None)
    # Lifecycle phase timings (ms). kill_ms is only set for single-execution sandboxes.
    create_ms: int | None = None
    upload_ms: int | None = None
    run_ms: int | None = None
    kill_ms: int | None = None

    @classmethod
    def new(
        cls,
        code: str,
        timeout_seconds: int,
        owner: str,
        source: Source = "api",
        agent_run_id: str | None = None,
    ) -> "ExecutionRecord":
        raw = code.encode("utf-8")
        return cls(
            id="exe_" + uuid.uuid4().hex,
            owner=owner,
            status=ExecutionStatus.QUEUED,
            code=code,
            code_sha256=hashlib.sha256(raw).hexdigest(),
            code_size=len(raw),
            timeout_seconds=timeout_seconds,
            source=source,
            agent_run_id=agent_run_id,
            created_at=utcnow(),
        )
