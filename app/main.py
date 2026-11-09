"""FastAPI application factory."""

from fastapi import FastAPI

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging

VERSION = "0.1.0"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.LOG_LEVEL, settings.secret_values())

    app = FastAPI(
        title="Agent Sandbox Runner",
        version=VERSION,
        description="Secure Python execution for AI agents on E2B cloud sandboxes.",
    )
    app.state.settings = settings

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": VERSION}

    return app
