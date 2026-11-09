"""AI agent endpoint."""

from fastapi import APIRouter, Request

from app.dependencies import LimitedOwner, api_error
from app.schemas.agents import AgentRunRequest, AgentRunResult
from app.schemas.errors import ErrorResponse
from app.services.agent_service import AgentService

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


@router.post(
    "/run",
    response_model=AgentRunResult,
    responses={
        401: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        503: {"model": ErrorResponse, "description": "No LLM configured"},
    },
    summary="Run a natural-language task with a tool-calling agent",
)
async def run_agent(body: AgentRunRequest, owner: LimitedOwner, request: Request) -> AgentRunResult:
    agent: AgentService | None = request.app.state.agent_service
    if agent is None:
        raise api_error(
            503, "agent_unavailable", "No LLM configured. Set LLM_API_KEY and LLM_MODEL."
        )
    return await agent.run(body.task, owner)
