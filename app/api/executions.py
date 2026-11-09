"""Code execution endpoints."""

from fastapi import APIRouter, Query, Response

from app.dependencies import Executions, Owner, api_error
from app.schemas.errors import ErrorResponse
from app.schemas.executions import ExecutionCreate, ExecutionOut

router = APIRouter(prefix="/api/v1/executions", tags=["executions"])

_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse, "description": "Missing or invalid API key"},
    422: {"model": ErrorResponse, "description": "Invalid request or policy violation"},
    429: {"model": ErrorResponse, "description": "Rate limited"},
}


@router.post(
    "",
    status_code=202,
    response_model=ExecutionOut,
    responses={200: {"model": ExecutionOut, "description": "Finished (wait=true)"}, **_ERRORS},
    summary="Submit Python code for sandboxed execution",
)
async def create_execution(
    body: ExecutionCreate,
    owner: Owner,
    svc: Executions,
    response: Response,
    wait: bool = Query(False, description="Block until the execution finishes."),
) -> ExecutionOut:
    rec = await svc.submit(body.code, body.timeout_seconds, owner)
    response.headers["Location"] = f"/api/v1/executions/{rec.id}"
    if wait:
        done = await svc.wait(rec.id, owner)
        if done is not None:
            rec = done
        if rec.status.is_terminal:
            response.status_code = 200
    return ExecutionOut.from_record(rec)


@router.get(
    "/{execution_id}",
    response_model=ExecutionOut,
    responses={404: {"model": ErrorResponse}, **_ERRORS},
    summary="Get an execution's status and result",
)
async def get_execution(execution_id: str, owner: Owner, svc: Executions) -> ExecutionOut:
    rec = await svc.get(execution_id, owner)
    if rec is None:
        raise api_error(404, "not_found", f"Execution {execution_id} not found.")
    return ExecutionOut.from_record(rec)
