"""Public demo API. No credentials are ever sent to or held by the browser.

Every spending request passes, in order: policy validation (free), Turnstile (if configured),
the per-visitor hourly limit, then the global daily budget. Only then is a sandbox or LLM used.
"""

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.core.config import Settings
from app.core.metrics import Metrics
from app.demo.examples import AGENT_EXAMPLES, EXAMPLES
from app.demo.guard import DailyBudget, VisitorLimiter, next_reset_iso, visitor_id
from app.demo.sse import last_event_id, sse_response
from app.demo.turnstile import Verifier
from app.dependencies import api_error
from app.schemas.executions import ExecutionOut
from app.services.agent_service import AgentLimits, AgentService
from app.services.events import EventBus
from app.services.execution_service import ExecutionPolicy, ExecutionService

DEMO_OWNER = "demo"
RECORDINGS_PATH = Path(__file__).with_name("recordings.json")

router = APIRouter(prefix="/demo", tags=["demo"])


@dataclass
class DemoContext:
    settings: Settings
    executions: ExecutionService
    agent: AgentService | None
    events: EventBus
    metrics: Metrics
    budget: DailyBudget
    visitors: VisitorLimiter
    turnstile: Verifier | None

    @property
    def policy(self) -> ExecutionPolicy:
        s = self.settings
        return ExecutionPolicy(
            s.DEMO_MAX_CODE_BYTES, s.DEMO_MAX_TIMEOUT_SECONDS, s.DEMO_DEFAULT_TIMEOUT_SECONDS
        )

    @property
    def agent_limits(self) -> AgentLimits:
        s = self.settings
        return AgentLimits(
            s.DEMO_AGENT_MAX_STEPS,
            s.DEMO_AGENT_MAX_TOOL_CALLS,
            s.DEMO_AGENT_TIMEOUT_SECONDS,
            s.DEMO_AGENT_MAX_TOKENS,
        )


def get_demo(request: Request) -> DemoContext:
    ctx: DemoContext | None = getattr(request.app.state, "demo", None)
    if ctx is None:
        raise HTTPException(404, detail={"code": "not_found", "message": "Demo is disabled."})
    return ctx


Demo = Annotated[DemoContext, Depends(get_demo)]


def client_ip(request: Request, trust_proxy: bool, hops: int = 1, header: str | None = None) -> str:
    """The visitor's address. `header` names a single-IP header the edge proxy always
    overwrites (Cloudflare's CF-Connecting-IP), which wins when present. Otherwise,
    behind `hops` trusted proxies that each append to X-Forwarded-For, the real
    client is `hops` entries from the right; anything further left was supplied by
    the client and cannot be trusted."""
    if trust_proxy:
        edge = request.headers.get(header, "").strip() if header else ""
        if edge:
            return edge
        fwd = request.headers.get("X-Forwarded-For", "")
        parts = [p.strip() for p in fwd.split(",") if p.strip()]
        if parts:
            return parts[-min(max(hops, 1), len(parts))]
    return request.client.host if request.client else "unknown"


class DemoExecutionCreate(BaseModel):
    code: str = Field(max_length=200_000)
    timeout_seconds: int | None = None
    turnstile_token: str | None = Field(default=None, max_length=4096)

    @field_validator("code")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("code must not be blank")
        return v


class DemoAgentCreate(BaseModel):
    task: str = Field(min_length=1, max_length=1000)
    turnstile_token: str | None = Field(default=None, max_length=4096)


async def _guard_spend(
    ctx: DemoContext,
    request: Request,
    token: str | None,
    kind: str,
    per_hour: int,
    daily_cap: int,
) -> None:
    s = ctx.settings
    ip = client_ip(request, s.TRUST_PROXY, s.TRUSTED_PROXY_HOPS, s.CLIENT_IP_HEADER)
    if ctx.turnstile is not None:
        if not token:
            raise api_error(403, "turnstile_required", "Bot check required.")
        if not await ctx.turnstile.verify(token, ip):
            raise api_error(403, "turnstile_failed", "Bot check failed. Please retry.")
    wait = ctx.visitors.check(visitor_id(ip), kind, per_hour)
    if wait is not None:
        raise api_error(
            429,
            "rate_limited",
            f"Demo limit is {per_hour} per hour per visitor.",
            headers={"Retry-After": str(max(1, math.ceil(wait)))},
        )
    if not await ctx.budget.try_consume(kind, daily_cap):
        raise api_error(
            429,
            "demo_budget_exhausted",
            "Today's demo budget is used up. It resets at midnight UTC.",
        )


@router.get("/status")
async def status(ctx: Demo) -> dict[str, Any]:
    s = ctx.settings
    runs_used = await ctx.budget.used("runs")
    agent_used = await ctx.budget.used("agent_runs")
    snap = ctx.metrics.snapshot()
    return {
        "agent_available": ctx.agent is not None,
        "turnstile_site_key": s.TURNSTILE_SITE_KEY if ctx.turnstile is not None else None,
        "repo_url": s.PUBLIC_REPO_URL,
        "model": s.LLM_MODEL if ctx.agent is not None else None,
        "budget": {
            "runs": {
                "total": s.DEMO_DAILY_RUNS,
                "remaining": max(0, s.DEMO_DAILY_RUNS - runs_used),
            },
            "agent_runs": {
                "total": s.DEMO_DAILY_AGENT_RUNS,
                "remaining": max(0, s.DEMO_DAILY_AGENT_RUNS - agent_used),
            },
            "resets_at": next_reset_iso(),
        },
        "limits": {
            "max_timeout_seconds": s.DEMO_MAX_TIMEOUT_SECONDS,
            "default_timeout_seconds": s.DEMO_DEFAULT_TIMEOUT_SECONDS,
            "max_code_bytes": s.DEMO_MAX_CODE_BYTES,
            "max_output_bytes": s.MAX_OUTPUT_BYTES,
            "runs_per_hour": s.DEMO_RUNS_PER_HOUR,
            "agent_runs_per_hour": s.DEMO_AGENT_RUNS_PER_HOUR,
            "agent_max_steps": s.DEMO_AGENT_MAX_STEPS,
            "agent_max_tool_calls": s.DEMO_AGENT_MAX_TOOL_CALLS,
            "internet": False,
        },
        "metrics": snap,
    }


@router.get("/examples")
async def examples(_ctx: Demo) -> list[dict[str, object]]:
    return EXAMPLES


@router.get("/agent/examples")
async def agent_examples(_ctx: Demo) -> list[str]:
    return AGENT_EXAMPLES


@router.get("/recordings")
async def recordings(_ctx: Demo) -> dict[str, Any]:
    if not RECORDINGS_PATH.exists():
        return {"executions": {}, "agent_runs": []}
    data: dict[str, Any] = json.loads(RECORDINGS_PATH.read_text(encoding="utf-8"))
    return data


@router.post("/executions", status_code=202, response_model=ExecutionOut)
async def create_execution(body: DemoExecutionCreate, ctx: Demo, request: Request) -> ExecutionOut:
    ctx.executions.check_policy(body.code, body.timeout_seconds, ctx.policy)  # free; 422 first
    s = ctx.settings
    await _guard_spend(
        ctx, request, body.turnstile_token, "runs", s.DEMO_RUNS_PER_HOUR, s.DEMO_DAILY_RUNS
    )
    rec = await ctx.executions.submit(body.code, body.timeout_seconds, DEMO_OWNER, ctx.policy)
    return ExecutionOut.from_record(rec)


@router.get("/executions/{execution_id}", response_model=ExecutionOut)
async def get_execution(execution_id: str, ctx: Demo) -> ExecutionOut:
    rec = await ctx.executions.get(execution_id, DEMO_OWNER)
    if rec is None:
        raise api_error(404, "not_found", "Execution not found.")
    return ExecutionOut.from_record(rec)


@router.get("/executions/{execution_id}/events")
async def execution_events(execution_id: str, ctx: Demo, request: Request) -> StreamingResponse:
    if not ctx.events.has(execution_id):
        if await ctx.executions.get(execution_id, DEMO_OWNER) is None:
            raise api_error(404, "not_found", "Execution not found.")
        # Evicted from memory: the client falls back to GET for the stored record.
        raise api_error(410, "stream_expired", "Live events expired; fetch the record instead.")
    return sse_response(ctx.events, execution_id, last_event_id(request))


@router.post("/agent/runs", status_code=202)
async def create_agent_run(body: DemoAgentCreate, ctx: Demo, request: Request) -> dict[str, str]:
    if ctx.agent is None:
        raise api_error(503, "agent_unavailable", "The AI agent is not configured on this server.")
    s = ctx.settings
    await _guard_spend(
        ctx,
        request,
        body.turnstile_token,
        "agent_runs",
        s.DEMO_AGENT_RUNS_PER_HOUR,
        s.DEMO_DAILY_AGENT_RUNS,
    )
    run_id = ctx.agent.start(body.task, DEMO_OWNER, limits=ctx.agent_limits, policy=ctx.policy)
    return {"run_id": run_id}


@router.get("/agent/runs/{run_id}/events")
async def agent_events(run_id: str, ctx: Demo, request: Request) -> StreamingResponse:
    if not ctx.events.has(run_id):
        raise api_error(404, "not_found", "Agent run not found or expired.")
    return sse_response(ctx.events, run_id, last_event_id(request))
