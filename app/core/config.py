"""Application settings, loaded from environment variables and `.env`."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Auth
    API_KEYS: SecretStr = SecretStr("")

    # E2B
    E2B_API_KEY: SecretStr | None = None
    SANDBOX_TEMPLATE: str | None = None
    SANDBOX_ALLOW_INTERNET: bool = False
    SANDBOX_CREATE_RETRIES: int = 3
    MAX_CONCURRENT_SANDBOXES: int = 5

    # Execution policy
    DEFAULT_TIMEOUT_SECONDS: int = 30
    MAX_TIMEOUT_SECONDS: int = 120
    MAX_CODE_BYTES: int = 100_000
    MAX_OUTPUT_BYTES: int = 65_536

    # API
    RATE_LIMIT_PER_MINUTE: int = 30
    DATABASE_PATH: str = "data/executions.db"
    LOG_LEVEL: str = "INFO"

    # LLM / agent
    LLM_API_KEY: SecretStr | None = None
    LLM_BASE_URL: str = "https://openrouter.ai/api/v1"
    LLM_MODEL: str | None = None
    AGENT_MAX_STEPS: int = 6
    AGENT_MAX_TOOL_CALLS: int = 4
    AGENT_TIMEOUT_SECONDS: float = 180
    AGENT_MAX_TOKENS: int = 1024

    # Public demo (/demo/*): no browser credentials, capped spend
    DEMO_ENABLED: bool = False
    DEMO_RUNS_PER_HOUR: int = 10
    DEMO_AGENT_RUNS_PER_HOUR: int = 3
    DEMO_DAILY_RUNS: int = 300
    DEMO_DAILY_AGENT_RUNS: int = 40
    DEMO_MAX_TIMEOUT_SECONDS: int = 15
    DEMO_DEFAULT_TIMEOUT_SECONDS: int = 10
    DEMO_MAX_CODE_BYTES: int = 10_000
    DEMO_AGENT_MAX_STEPS: int = 4
    DEMO_AGENT_MAX_TOOL_CALLS: int = 2
    DEMO_AGENT_TIMEOUT_SECONDS: float = 90
    DEMO_AGENT_MAX_TOKENS: int = 800
    TURNSTILE_SITE_KEY: str | None = None
    TURNSTILE_SECRET_KEY: SecretStr | None = None
    TRUST_PROXY: bool = False  # honour X-Forwarded-For (only behind a trusted proxy)
    TRUSTED_PROXY_HOPS: int = 1  # proxies in front of the app that append to X-Forwarded-For
    PUBLIC_REPO_URL: str | None = None

    def api_key_list(self) -> list[str]:
        return [k.strip() for k in self.API_KEYS.get_secret_value().split(",") if k.strip()]

    def secret_values(self) -> list[str]:
        """Every configured secret, for log redaction."""
        values = self.api_key_list()
        for s in (self.E2B_API_KEY, self.LLM_API_KEY, self.TURNSTILE_SECRET_KEY):
            if s is not None and s.get_secret_value():
                values.append(s.get_secret_value())
        return values


@lru_cache
def get_settings() -> Settings:
    return Settings()
