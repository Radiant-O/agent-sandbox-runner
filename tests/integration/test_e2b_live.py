"""Live E2B tests. Run with: pytest -m integration  (needs E2B_API_KEY in env or .env)."""

import pytest

from app.core.config import Settings
from app.core.metrics import Metrics
from app.sandbox.e2b_backend import E2BSandboxBackend

pytestmark = pytest.mark.integration


@pytest.fixture
def live_backend() -> E2BSandboxBackend:
    s = Settings()
    if s.E2B_API_KEY is None or not s.E2B_API_KEY.get_secret_value():
        pytest.skip("E2B_API_KEY not set")
    return E2BSandboxBackend(s, Metrics())


async def test_live_cases(live_backend: E2BSandboxBackend) -> None:
    # One sandbox for all cases keeps this test cheap.
    async with live_backend.session(lifetime_seconds=120) as s:
        ok = await s.run_python("print(2 + 2)", 20)
        assert ok.exit_code == 0, ok
        assert ok.stdout == "4\n"

        err = await s.run_python("1/0", 20)
        assert err.exit_code == 1
        assert "ZeroDivisionError" in err.stderr

        slow = await s.run_python("import time; time.sleep(30)", 3)
        assert slow.timed_out is True

        net = await s.run_python(
            "import urllib.request; urllib.request.urlopen('https://example.com', timeout=5)",
            20,
        )
        assert net.exit_code not in (0, None), net
