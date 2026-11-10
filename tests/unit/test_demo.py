"""Public demo surface: no credentials in the browser, capped spend, live streams."""

import json
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager

from app.core.config import Settings
from app.llm.base import LLMTurn, ToolCall
from app.main import create_app
from tests.fakes import FakeSandboxBackend, ScriptedLLM

ClientFactory = Callable[..., AbstractAsyncContextManager[httpx.AsyncClient]]


class StubVerifier:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.calls: list[tuple[str, str]] = []

    async def verify(self, token: str, remote_ip: str) -> bool:
        self.calls.append((token, remote_ip))
        return self.ok


@pytest.fixture
def demo_client(settings: Settings) -> ClientFactory:
    settings.DEMO_ENABLED = True

    @asynccontextmanager
    async def factory(
        backend: FakeSandboxBackend | None = None,
        llm: Any = None,
        turnstile: StubVerifier | None = None,
        static_dir: Path | None = None,
        **overrides: object,
    ) -> AsyncIterator[httpx.AsyncClient]:
        for k, v in overrides.items():
            setattr(settings, k, v)
        app = create_app(
            settings,
            backend=backend or FakeSandboxBackend(),
            llm=llm,
            turnstile=turnstile,
            static_dir=static_dir,
        )
        async with LifespanManager(app) as mgr:
            transport = httpx.ASGITransport(app=mgr.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                yield c

    return factory


def parse_sse(body: str) -> list[dict[str, Any]]:
    events = []
    for block in body.strip().split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if not line.startswith(":")
        )
        if "event" in fields:
            events.append(
                {"type": fields["event"], "id": fields.get("id"), **json.loads(fields["data"])}
            )
    return events


async def test_demo_disabled_is_404(settings: Settings) -> None:
    app = create_app(settings, backend=FakeSandboxBackend())
    async with LifespanManager(app) as mgr:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=mgr.app), base_url="http://t"
        ) as c:
            r = await c.get("/demo/status")
    assert r.status_code == 404


async def test_status_exposes_budget_limits_and_site_key(demo_client: ClientFactory) -> None:
    async with demo_client(turnstile=StubVerifier(), TURNSTILE_SITE_KEY="site-123") as c:
        s = (await c.get("/demo/status")).json()
    assert s["turnstile_site_key"] == "site-123"
    assert s["budget"]["runs"]["remaining"] == 300
    assert s["budget"]["agent_runs"]["remaining"] == 40
    assert s["limits"]["max_timeout_seconds"] == 15
    assert s["agent_available"] is False
    assert "secret" not in json.dumps(s).lower()


async def test_run_without_any_key_and_stream_events(demo_client: ClientFactory) -> None:
    async with demo_client() as c:
        r = await c.post("/demo/executions", json={"code": "print(1)"})
        assert r.status_code == 202
        exec_id = r.json()["id"]
        stream = await c.get(f"/demo/executions/{exec_id}/events")
        got = await c.get(f"/demo/executions/{exec_id}")
    assert stream.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(stream.text)
    types = [e["type"] for e in events]
    assert types[0] == "queued" and types[-1] == "finished"
    assert "sandbox_created" in types and "sandbox_killed" in types
    assert got.json()["status"] == "succeeded"


async def test_stream_resumes_after_last_event_id(demo_client: ClientFactory) -> None:
    async with demo_client() as c:
        exec_id = (await c.post("/demo/executions", json={"code": "print(1)"})).json()["id"]
        full = parse_sse((await c.get(f"/demo/executions/{exec_id}/events")).text)
        resumed = parse_sse(
            (await c.get(f"/demo/executions/{exec_id}/events", headers={"Last-Event-ID": "3"})).text
        )
    assert [e["id"] for e in resumed] == [e["id"] for e in full][3:]


async def test_demo_policy_is_tighter(demo_client: ClientFactory) -> None:
    async with demo_client() as c:
        too_long = await c.post(
            "/demo/executions", json={"code": "print(1)", "timeout_seconds": 30}
        )
        too_big = await c.post("/demo/executions", json={"code": "x" * 10_001})
    assert (
        too_long.status_code == 422 and too_long.json()["error"]["code"] == "timeout_out_of_range"
    )
    assert too_big.status_code == 422 and too_big.json()["error"]["code"] == "code_too_large"


async def test_per_visitor_hourly_limit(demo_client: ClientFactory) -> None:
    async with demo_client(DEMO_RUNS_PER_HOUR=2) as c:
        codes = [
            (await c.post("/demo/executions", json={"code": "print(1)"})).status_code
            for _ in range(3)
        ]
        r = await c.post("/demo/executions", json={"code": "print(1)"})
    assert codes == [202, 202, 429]
    assert r.json()["error"]["code"] == "rate_limited"
    assert int(r.headers["Retry-After"]) >= 1


async def test_daily_budget_exhausts_and_policy_errors_do_not_consume(
    demo_client: ClientFactory,
) -> None:
    async with demo_client(DEMO_DAILY_RUNS=2) as c:
        await c.post("/demo/executions", json={"code": "x" * 20_000})  # 422, no spend
        ok = [
            (await c.post("/demo/executions", json={"code": "print(1)"})).status_code
            for _ in range(2)
        ]
        r = await c.post("/demo/executions", json={"code": "print(1)"})
        status = (await c.get("/demo/status")).json()
    assert ok == [202, 202]
    assert r.status_code == 429 and r.json()["error"]["code"] == "demo_budget_exhausted"
    assert status["budget"]["runs"]["remaining"] == 0


async def test_turnstile_required_when_configured(demo_client: ClientFactory) -> None:
    verifier = StubVerifier(ok=False)
    async with demo_client(turnstile=verifier) as c:
        missing = await c.post("/demo/executions", json={"code": "print(1)"})
        bad = await c.post("/demo/executions", json={"code": "print(1)", "turnstile_token": "t"})
        verifier.ok = True
        good = await c.post("/demo/executions", json={"code": "print(1)", "turnstile_token": "t"})
    assert missing.status_code == 403 and missing.json()["error"]["code"] == "turnstile_required"
    assert bad.status_code == 403 and bad.json()["error"]["code"] == "turnstile_failed"
    assert good.status_code == 202
    assert verifier.calls[0][0] == "t"


async def test_agent_run_streams_to_finished(demo_client: ClientFactory) -> None:
    llm = ScriptedLLM(
        [
            LLMTurn(
                text=None, tool_calls=[ToolCall("c1", "execute_python", '{"code":"print(4)"}')]
            ),
            LLMTurn(text="It printed 4."),
        ]
    )
    async with demo_client(llm=llm) as c:
        r = await c.post("/demo/agent/runs", json={"task": "print four"})
        assert r.status_code == 202
        run_id = r.json()["run_id"]
        events = parse_sse((await c.get(f"/demo/agent/runs/{run_id}/events")).text)
        status = (await c.get("/demo/status")).json()
    types = [e["type"] for e in events]
    assert types[0] == "started" and types[-1] == "finished"
    assert "tool_call" in types and "tool_result" in types
    assert events[-1]["data"]["run"]["answer"] == "It printed 4."
    assert status["budget"]["agent_runs"]["remaining"] == 39


async def test_agent_unavailable_without_llm(demo_client: ClientFactory) -> None:
    async with demo_client() as c:
        r = await c.post("/demo/agent/runs", json={"task": "hi"})
    assert r.status_code == 503


async def test_examples_listed(demo_client: ClientFactory) -> None:
    async with demo_client() as c:
        ex = (await c.get("/demo/examples")).json()
    assert {e["id"] for e in ex} >= {"success", "runtime_error", "timeout", "flood", "network"}


def test_demo_with_internet_enabled_refuses_to_start(settings: Settings) -> None:
    settings.DEMO_ENABLED = True
    settings.SANDBOX_ALLOW_INTERNET = True
    with pytest.raises(ValueError, match="internet"):
        create_app(settings, backend=FakeSandboxBackend())


async def test_serves_built_ui_and_spa_fallback(demo_client: ClientFactory, tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<html>console</html>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    async with demo_client(static_dir=tmp_path) as c:
        root = await c.get("/")
        asset = await c.get("/assets/app.js")
        deep = await c.get("/agent")
        health = await c.get("/health")
        api_404 = await c.get("/api/v1/nope")
    assert "console" in root.text and asset.status_code == 200
    assert "console" in deep.text  # client-side route
    assert health.json()["status"] == "ok"
    assert api_404.status_code == 404


def test_examples_are_grouped_for_the_console() -> None:
    from app.demo.examples import EXAMPLE_GROUPS, EXAMPLES

    assert {e["group"] for e in EXAMPLES} == set(EXAMPLE_GROUPS)
    order = [EXAMPLE_GROUPS.index(str(e["group"])) for e in EXAMPLES]
    assert order == sorted(order)  # listed group by group
