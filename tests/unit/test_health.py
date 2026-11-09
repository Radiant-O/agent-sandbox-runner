import httpx

from app.core.config import Settings
from app.main import create_app


async def test_health_ok(settings: Settings) -> None:
    app = create_app(settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
