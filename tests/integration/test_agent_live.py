"""Live agent test: real OpenRouter + real E2B. Costs a little credit; run sparingly.

pytest -m integration tests/integration/test_agent_live.py
"""

from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.metrics import Metrics
from app.llm.openai_compat import OpenAICompatibleProvider
from app.sandbox.e2b_backend import E2BSandboxBackend
from app.services.agent_service import AgentService
from app.services.execution_service import ExecutionService
from app.store import ExecutionStore

pytestmark = pytest.mark.integration


async def test_agent_computes_fibonacci(tmp_path: Path) -> None:
    s = Settings()
    if not (s.E2B_API_KEY and s.LLM_API_KEY and s.LLM_MODEL):
        pytest.skip("E2B_API_KEY, LLM_API_KEY and LLM_MODEL are required")
    metrics = Metrics()
    store = ExecutionStore(str(tmp_path / "live.db"))
    await store.init()
    try:
        execs = ExecutionService(store, E2BSandboxBackend(s, metrics), metrics, s)
        llm = OpenAICompatibleProvider(
            s.LLM_API_KEY.get_secret_value(), s.LLM_BASE_URL, s.LLM_MODEL
        )
        res = await AgentService(llm, execs, metrics, s).run(
            "What is the 20th Fibonacci number (F1=F2=1)? Compute it with code.", "live"
        )
    finally:
        await store.close()
    print(res.model_dump_json(indent=2))
    assert res.stop_reason == "completed", res
    assert res.any_execution_succeeded
    assert res.answer is not None and "6765" in res.answer
