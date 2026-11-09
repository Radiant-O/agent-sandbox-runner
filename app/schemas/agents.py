"""Schemas for the agent endpoint."""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.executions import ExecutionOut

StopReason = Literal["completed", "step_limit", "tool_call_limit", "time_limit", "llm_error"]


class AgentRunRequest(BaseModel):
    task: str = Field(
        min_length=1,
        max_length=4000,
        description="Natural-language task for the agent.",
        examples=["What is the 20th Fibonacci number? Compute it."],
    )


class AgentRunResult(BaseModel):
    id: str
    stop_reason: StopReason = Field(
        description="Why the run ended. Only 'completed' carries an answer."
    )
    answer: str | None = Field(
        description="The model's final answer. Verify claims against `executions`."
    )
    executions: list[ExecutionOut] = Field(
        description="Every sandbox execution in this run, as recorded by the backend."
    )
    any_execution_succeeded: bool = Field(
        description="Computed from execution records, never from model text."
    )
    steps: int
    tool_calls: int
