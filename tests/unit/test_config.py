from app.core.config import Settings


def test_api_keys_parsed_from_comma_list() -> None:
    s = Settings(_env_file=None, API_KEYS="a, b,,")
    assert s.api_key_list() == ["a", "b"]


def test_timeout_defaults() -> None:
    s = Settings(_env_file=None, API_KEYS="k")
    assert s.DEFAULT_TIMEOUT_SECONDS == 30
    assert s.MAX_TIMEOUT_SECONDS == 120
    assert s.SANDBOX_ALLOW_INTERNET is False
    assert s.MAX_CONCURRENT_SANDBOXES == 5
