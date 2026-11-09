"""FastAPI application factory."""

import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from app.api import executions, system
from app.api.system import VERSION
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, request_id_var
from app.core.metrics import Metrics
from app.core.security import RateLimiter
from app.sandbox.base import SandboxBackend
from app.services.execution_service import ExecutionService, PolicyViolation
from app.store import ExecutionStore

log = logging.getLogger("app.access")


def _error(request: Request, status: int, code: str, message: str, **kw: Any) -> JSONResponse:
    rid = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "request_id": rid}},
        **kw,
    )


def create_app(
    settings: Settings | None = None,
    *,
    backend: SandboxBackend | None = None,
    llm: object | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.LOG_LEVEL, settings.secret_values())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        metrics = Metrics()
        store = ExecutionStore(settings.DATABASE_PATH)
        await store.init()
        if backend is None:
            from app.sandbox.e2b_backend import E2BSandboxBackend

            sandbox_backend: SandboxBackend = E2BSandboxBackend(settings, metrics)
        else:
            sandbox_backend = backend
        svc = ExecutionService(store, sandbox_backend, metrics, settings)
        await svc.recover()
        app.state.metrics = metrics
        app.state.execution_service = svc
        app.state.rate_limiter = RateLimiter(settings.RATE_LIMIT_PER_MINUTE)
        app.state.llm = llm
        try:
            yield
        finally:
            await svc.shutdown()
            await store.close()

    app = FastAPI(
        title="Agent Sandbox Runner",
        version=VERSION,
        description=(
            "Run untrusted Python inside isolated E2B cloud sandboxes, directly or through "
            "a tool-calling AI agent. Authenticate with the `X-API-Key` header."
        ),
        lifespan=lifespan,
    )
    app.state.settings = settings

    @app.middleware("http")
    async def request_context(request: Request, call_next: RequestResponseEndpoint) -> Response:
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = rid
        token = request_id_var.set(rid)
        start = time.monotonic()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = rid
            log.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": int((time.monotonic() - start) * 1000),
                },
            )
            return response
        finally:
            request_id_var.reset(token)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict):
            code, message = exc.detail["code"], exc.detail["message"]
        else:
            code, message = f"http_{exc.status_code}", str(exc.detail)
        return _error(request, exc.status_code, code, message, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", ()))
        return _error(request, 422, "invalid_request", f"{loc}: {first.get('msg', 'invalid')}")

    @app.exception_handler(PolicyViolation)
    async def policy_error(request: Request, exc: PolicyViolation) -> JSONResponse:
        return _error(request, 422, exc.code, exc.message)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        logging.getLogger("app").exception("unhandled error")
        return _error(request, 500, "internal_error", "Internal server error.")

    app.include_router(system.router)
    app.include_router(executions.router)
    return app
