"""Server-Sent Events response over an EventBus stream."""

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator

from fastapi import Request
from fastapi.responses import StreamingResponse

from app.services.events import EventBus

HEARTBEAT_SECONDS = 15.0


def _format(event: dict[str, object]) -> str:
    payload = json.dumps({"ts": event["ts"], "data": event["data"]}, default=str)
    return f"id: {event['seq']}\nevent: {event['type']}\ndata: {payload}\n\n"


def last_event_id(request: Request) -> int:
    raw = request.headers.get("Last-Event-ID") or request.query_params.get("after") or "0"
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def sse_response(bus: EventBus, stream_id: str, after_seq: int) -> StreamingResponse:
    async def body() -> AsyncIterator[str]:
        yield "retry: 2000\n\n"
        events = bus.subscribe(stream_id, after_seq=after_seq)
        nxt: asyncio.Task[dict[str, object]] | None = None
        try:
            while True:
                if nxt is None:
                    nxt = asyncio.ensure_future(events.__anext__())
                done, _ = await asyncio.wait({nxt}, timeout=HEARTBEAT_SECONDS)
                if not done:
                    yield ": keep-alive\n\n"
                    continue
                try:
                    event = nxt.result()
                except StopAsyncIteration:
                    return
                nxt = None
                yield _format(event)
        finally:
            if nxt is not None:
                nxt.cancel()
            with contextlib.suppress(Exception):
                await events.aclose()  # type: ignore[attr-defined]

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
