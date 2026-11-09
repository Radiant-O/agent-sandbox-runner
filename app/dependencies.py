"""FastAPI dependencies: auth, rate limiting, service lookup."""

import hmac
import math
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyHeader

from app.core.metrics import Metrics
from app.core.security import RateLimiter, owner_id
from app.services.execution_service import ExecutionService

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def api_error(
    status: int, code: str, message: str, headers: dict[str, str] | None = None
) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message}, headers=headers)


async def require_api_key(
    request: Request, api_key: Annotated[str | None, Depends(_api_key_header)]
) -> str:
    """Authenticate. Returns the caller's owner id."""
    valid = request.app.state.settings.api_key_list()
    matched = api_key is not None and any(
        hmac.compare_digest(api_key.encode(), k.encode()) for k in valid
    )
    if not matched or api_key is None:
        raise api_error(401, "unauthorized", "Missing or invalid X-API-Key header.")
    return owner_id(api_key)


async def rate_limited(request: Request, owner: Annotated[str, Depends(require_api_key)]) -> str:
    """Authenticate and charge the caller's rate-limit budget.

    Applied to requests that create sandboxes or spend LLM tokens. Cheap reads (polling an
    execution, metrics) are authenticated but not charged, so polling cannot lock a client out.
    """
    limiter: RateLimiter = request.app.state.rate_limiter
    retry_after = limiter.check(owner)
    if retry_after is not None:
        raise api_error(
            429,
            "rate_limited",
            "Rate limit exceeded.",
            headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
        )
    return owner


def get_execution_service(request: Request) -> ExecutionService:
    svc: ExecutionService = request.app.state.execution_service
    return svc


def get_metrics(request: Request) -> Metrics:
    m: Metrics = request.app.state.metrics
    return m


Owner = Annotated[str, Depends(require_api_key)]
LimitedOwner = Annotated[str, Depends(rate_limited)]
Executions = Annotated[ExecutionService, Depends(get_execution_service)]
MetricsDep = Annotated[Metrics, Depends(get_metrics)]
