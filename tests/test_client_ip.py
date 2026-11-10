from starlette.requests import Request

from app.demo.router import client_ip


def _req(xff: str | None, peer: str = "10.0.0.9") -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff is not None else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234)})


def test_ignores_forwarded_header_without_a_trusted_proxy() -> None:
    assert client_ip(_req("1.2.3.4"), trust_proxy=False) == "10.0.0.9"


def test_uses_the_entry_the_proxy_appended() -> None:
    assert client_ip(_req("203.0.113.7"), trust_proxy=True) == "203.0.113.7"


def test_a_spoofed_leading_entry_cannot_change_the_visitor() -> None:
    # The client sent "X-Forwarded-For: 6.6.6.6"; the platform proxy appended the real address.
    assert client_ip(_req("6.6.6.6, 203.0.113.7"), trust_proxy=True) == "203.0.113.7"


def test_extra_proxy_hops_are_skipped_from_the_right() -> None:
    req = _req("6.6.6.6, 203.0.113.7, 172.16.0.1")
    assert client_ip(req, trust_proxy=True, hops=2) == "203.0.113.7"


def test_falls_back_to_the_peer_when_the_header_is_missing() -> None:
    assert client_ip(_req(None), trust_proxy=True) == "10.0.0.9"
