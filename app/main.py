"""FastAPI application factory."""

import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from app.api import agents, executions, system
from app.api.system import VERSION
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, request_id_var
from app.core.metrics import Metrics
from app.core.security import RateLimiter
from app.demo import router as demo_router
from app.demo.guard import DailyBudget, VisitorLimiter
from app.demo.turnstile import TurnstileVerifier, Verifier
from app.llm.base import LLMProvider
from app.llm.openai_compat import OpenAICompatibleProvider
from app.sandbox.base import SandboxBackend
from app.services.agent_service import AgentService
from app.services.events import EventBus
from app.services.execution_service import ExecutionService, PolicyViolation
from app.store import ExecutionStore

log = logging.getLogger("app.access")

DEFAULT_STATIC_DIR = Path(__file__).with_name("static")
_NOT_SPA_PREFIXES = ("api/", "demo/", "docs", "redoc", "openapi.json", "health", "metrics")


class SPAStaticFiles(StaticFiles):
    """Serve the built console; unknown client-side routes fall back to index.html."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            rel = path.replace("\\", "/")  # Starlette uses OS separators (Windows)
            if exc.status_code != 404 or rel.startswith(_NOT_SPA_PREFIXES) or "." in rel:
                raise
            return await super().get_response("index.html", scope)


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
    llm: LLMProvider | None = None,
    turnstile: Verifier | None = None,
    static_dir: Path | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    if settings.DEMO_ENABLED and settings.SANDBOX_ALLOW_INTERNET:
        raise ValueError("Refusing to start: the public demo requires sandbox internet off.")
    if turnstile is None and settings.TURNSTILE_SECRET_KEY is not None:
        secret = settings.TURNSTILE_SECRET_KEY.get_secret_value()
        if secret:
            turnstile = TurnstileVerifier(secret)
    static_root = static_dir or DEFAULT_STATIC_DIR
    configure_logging(settings.LOG_LEVEL, settings.secret_values())
    llm_key = settings.LLM_API_KEY.get_secret_value() if settings.LLM_API_KEY else ""
    if llm is None and llm_key and settings.LLM_MODEL:
        llm = OpenAICompatibleProvider(
            api_key=llm_key,
            base_url=settings.LLM_BASE_URL,
            model=settings.LLM_MODEL,
        )

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
        events = EventBus()
        svc = ExecutionService(store, sandbox_backend, metrics, settings, events=events)
        await svc.recover()
        app.state.metrics = metrics
        app.state.execution_service = svc
        app.state.rate_limiter = RateLimiter(settings.RATE_LIMIT_PER_MINUTE)
        agent = AgentService(llm, svc, metrics, settings, events=events) if llm else None
        app.state.agent_service = agent
        if settings.DEMO_ENABLED:
            budget = DailyBudget(store.db)
            await budget.init()
            app.state.demo = demo_router.DemoContext(
                settings=settings,
                executions=svc,
                agent=agent,
                events=events,
                metrics=metrics,
                budget=budget,
                visitors=VisitorLimiter(),
                turnstile=turnstile,
            )
        try:
            yield
        finally:
            if agent is not None:
                await agent.shutdown()
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
    app.include_router(agents.router)
    app.include_router(demo_router.router)
    if (static_root / "index.html").exists():
        app.mount("/", SPAStaticFiles(directory=static_root, html=True), name="console")
    return app
