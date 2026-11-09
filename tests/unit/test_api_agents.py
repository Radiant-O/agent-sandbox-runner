import httpx
from asgi_lifespan import LifespanManager

from app.core.config import Settings
from app.llm.base import LLMTurn
from app.main import create_app
from tests.fakes import FakeSandboxBackend, ScriptedLLM

KEY = {"X-API-Key": "test-key"}


async def _post(app: object, body: dict[str, object]) -> httpx.Response:
    async with LifespanManager(app) as mgr:  # type: ignore[arg-type]
        transport = httpx.ASGITransport(app=mgr.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            return await c.post("/api/v1/agent/run", json=body, headers=KEY)


async def test_agent_endpoint_503_without_llm(settings: Settings) -> None:
    app = create_app(settings, backend=FakeSandboxBackend(), llm=None)
    r = await _post(app, {"task": "hi"})
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "agent_unavailable"


async def test_agent_endpoint_runs(settings: Settings) -> None:
    llm = ScriptedLLM([LLMTurn(text="Hello!")])
    app = create_app(settings, backend=FakeSandboxBackend(), llm=llm)
    r = await _post(app, {"task": "say hello"})
    assert r.status_code == 200
    body = r.json()
    assert body["stop_reason"] == "completed"
    assert body["answer"] == "Hello!"
    assert body["id"].startswith("run_")


async def test_agent_endpoint_rejects_empty_task(settings: Settings) -> None:
    app = create_app(settings, backend=FakeSandboxBackend(), llm=ScriptedLLM([]))
    r = await _post(app, {"task": ""})
    assert r.status_code == 422
