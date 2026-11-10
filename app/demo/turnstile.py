"""Cloudflare Turnstile server-side verification (bot protection for the public demo)."""

import logging
from typing import Protocol

import httpx

log = logging.getLogger(__name__)

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


class Verifier(Protocol):
    async def verify(self, token: str, remote_ip: str) -> bool: ...


class TurnstileVerifier:
    def __init__(self, secret: str, client: httpx.AsyncClient | None = None) -> None:
        self._secret = secret
        self._client = client

    async def verify(self, token: str, remote_ip: str) -> bool:
        data = {"secret": self._secret, "response": token, "remoteip": remote_ip}
        try:
            if self._client is not None:
                r = await self._client.post(SITEVERIFY_URL, data=data, timeout=10)
            else:
                async with httpx.AsyncClient() as c:
                    r = await c.post(SITEVERIFY_URL, data=data, timeout=10)
            ok = bool(r.json().get("success"))
        except (httpx.HTTPError, ValueError):
            # Fail closed: if we cannot verify, we do not spend.
            log.warning("turnstile verification unavailable")
            return False
        if not ok:
            log.info("turnstile token rejected")
        return ok
