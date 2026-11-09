from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import httpx
import pytest
from asgi_lifespan import LifespanManager
from pydantic import SecretStr

from app.core.config import Settings
from app.main import create_app
from tests.fakes import FakeSandboxBackend

ClientFactory = Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]]
KEY = {"X-API-Key": "test-key"}


@pytest.fixture
def client_for(settings: Settings) -> ClientFactory:
    @asynccontextmanager
    async def factory(
        backend: FakeSandboxBackend | None = None, **overrides: object
    ) -> AsyncIterator[httpx.AsyncClient]:
        for k, v in overrides.items():
            setattr(settings, k, v)
        app = create_app(settings, backend=backend or FakeSandboxBackend())
        async with LifespanManager(app) as mgr:
            transport = httpx.ASGITransport(app=mgr.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                yield c

    return factory


async def test_missing_key_401_envelope(client_for: ClientFactory) -> None:
    async with client_for() as c:
        r = await c.post("/api/v1/executions", json={"code": "print(1)"})
    assert r.status_code == 401
    body = r.json()
    assert body["error"]["code"] == "unauthorized"
    assert body["error"]["request_id"]


async def test_wrong_key_401(client_for: ClientFactory) -> None:
    async with client_for() as c:
        r = await c.get("/api/v1/executions/exe_x", headers={"X-API-Key": "nope"})
    assert r.status_code == 401


async def test_submit_wait_returns_200_succeeded(client_for: ClientFactory) -> None:
    async with client_for() as c:
        r = await c.post("/api/v1/executions?wait=true", json={"code": "print(1)"}, headers=KEY)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "succeeded"
    assert body["exit_code"] == 0
    assert "code" not in body and "owner" not in body


async def test_submit_async_returns_202_then_get(client_for: ClientFactory) -> None:
    async with client_for(FakeSandboxBackend(delay=0.05)) as c:
        r = await c.post("/api/v1/executions", json={"code": "print(1)"}, headers=KEY)
        assert r.status_code == 202
        assert r.json()["status"] == "queued"
        exec_id = r.json()["id"]
        assert r.headers["Location"] == f"/api/v1/executions/{exec_id}"
        r2 = await c.get(f"/api/v1/executions/{exec_id}", headers=KEY)
    assert r2.status_code == 200
    assert r2.json()["id"] == exec_id


async def test_get_other_owner_404(client_for: ClientFactory) -> None:
    async with client_for(API_KEYS=SecretStr("key-a,key-b")) as c:
        r = await c.post(
            "/api/v1/executions?wait=true",
            json={"code": "print(1)"},
            headers={"X-API-Key": "key-a"},
        )
        exec_id = r.json()["id"]
        r2 = await c.get(f"/api/v1/executions/{exec_id}", headers={"X-API-Key": "key-b"})
    assert r2.status_code == 404
    assert r2.json()["error"]["code"] == "not_found"


async def test_code_too_large_422_code_too_large(client_for: ClientFactory) -> None:
    async with client_for(MAX_CODE_BYTES=5) as c:
        r = await c.post("/api/v1/executions", json={"code": "print(123)"}, headers=KEY)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "code_too_large"


async def test_invalid_body_422_envelope(client_for: ClientFactory) -> None:
    async with client_for() as c:
        r = await c.post("/api/v1/executions", json={"code": "   "}, headers=KEY)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_request"


async def test_rate_limit_429_with_retry_after(client_for: ClientFactory) -> None:
    async with client_for(RATE_LIMIT_PER_MINUTE=2) as c:
        codes = [
            (await c.post("/api/v1/executions", json={"code": "print(1)"}, headers=KEY)).status_code
            for _ in range(3)
        ]
        r = await c.post("/api/v1/executions", json={"code": "print(1)"}, headers=KEY)
    assert codes == [202, 202, 429]
    assert r.json()["error"]["code"] == "rate_limited"
    assert int(r.headers["Retry-After"]) >= 1


async def test_polling_reads_do_not_consume_submit_budget(client_for: ClientFactory) -> None:
    """Polling a running execution once a second must not lock the client out."""
    async with client_for(RATE_LIMIT_PER_MINUTE=2) as c:
        r = await c.post("/api/v1/executions", json={"code": "print(1)"}, headers=KEY)
        exec_id = r.json()["id"]
        polls = [
            (await c.get(f"/api/v1/executions/{exec_id}", headers=KEY)).status_code
            for _ in range(20)
        ]
        metrics = await c.get("/metrics", headers=KEY)
    assert set(polls) == {200}
    assert metrics.status_code == 200


async def test_request_id_echoed(client_for: ClientFactory) -> None:
    async with client_for() as c:
        r = await c.get("/health", headers={"X-Request-ID": "abc-123"})
        r2 = await c.get("/health")
    assert r.headers["X-Request-ID"] == "abc-123"
    assert r2.headers["X-Request-ID"]


async def test_metrics_counts_execution(client_for: ClientFactory) -> None:
    async with client_for() as c:
        await c.post("/api/v1/executions?wait=true", json={"code": "print(1)"}, headers=KEY)
        r = await c.get("/metrics", headers=KEY)
        unauth = await c.get("/metrics")
    assert r.json()["executions_by_status"] == {"succeeded": 1}
    assert unauth.status_code == 401


async def test_openapi_has_execution_paths(client_for: ClientFactory) -> None:
    async with client_for() as c:
        spec = (await c.get("/openapi.json")).json()
    assert "/api/v1/executions" in spec["paths"]
    assert "/api/v1/executions/{execution_id}" in spec["paths"]
