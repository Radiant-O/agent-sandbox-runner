import io
import json
import logging

from app.core.logging import configure_logging, request_id_var


def _capture(secrets: list[str]) -> tuple[logging.Logger, io.StringIO]:
    configure_logging("INFO", secrets)
    stream = io.StringIO()
    root = logging.getLogger()
    root.handlers[0].setStream(stream)  # type: ignore[attr-defined]
    return logging.getLogger("t"), stream


def test_log_line_is_json_with_request_id() -> None:
    log, stream = _capture([])
    token = request_id_var.set("req-1")
    try:
        log.info("hello", extra={"code_size": 3})
    finally:
        request_id_var.reset(token)
    line = json.loads(stream.getvalue().strip().splitlines()[-1])
    assert line["msg"] == "hello"
    assert line["request_id"] == "req-1"
    assert line["level"] == "INFO"
    assert line["code_size"] == 3


def test_secret_redacted_in_logs() -> None:
    log, stream = _capture(["sk-123"])
    log.info("key=sk-123")
    out = stream.getvalue()
    assert "sk-123" not in out
    assert "***" in out
