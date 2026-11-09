from pathlib import Path

import pytest

from app.core.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        API_KEYS="test-key",
        DATABASE_PATH=str(tmp_path / "test.db"),
        E2B_API_KEY=None,
        LLM_API_KEY=None,
    )
