"""Request/response schemas for the executions API."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.domain import ErrorCategory, ExecutionRecord, ExecutionStatus, Source


class ExecutionCreate(BaseModel):
    code: str = Field(description="Python source to execute.", examples=["print(2 + 2)"])
    timeout_seconds: int | None = Field(
        default=None, description="Execution timeout. Defaults to the server default."
    )

    @field_validator("code")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("code must not be blank")
        return v


class ExecutionOut(BaseModel):
    id: str
    status: ExecutionStatus
    source: Source
    agent_run_id: str | None
    code_sha256: str
    code_size: int
    timeout_seconds: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    exit_code: int | None
    error_category: ErrorCategory | None
    error_message: str | None
    exception_type: str | None
    sandbox_id: str | None

    @classmethod
    def from_record(cls, rec: ExecutionRecord) -> "ExecutionOut":
        data = {k: v for k, v in rec.__dict__.items() if k not in ("code", "owner")}
        return cls(**data)
