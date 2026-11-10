"""Health and metrics endpoints."""

from typing import Any

from fastapi import APIRouter

from app.dependencies import MetricsDep, Owner

VERSION = "0.1.0"

router = APIRouter(tags=["system"])


@router.get("/health", summary="Liveness check (no auth)")
@router.head("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok", "version": VERSION}


@router.get("/metrics", summary="Execution and sandbox metrics")
async def metrics(_owner: Owner, m: MetricsDep) -> dict[str, Any]:
    return m.snapshot()
