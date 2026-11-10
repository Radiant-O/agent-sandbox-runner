"""In-process event bus with per-stream replay, feeding the SSE endpoints.

Single-process by design (like the rate limiter): streams live in memory, are bounded,
and closed streams are evicted oldest-first once `max_streams` is exceeded.
"""

import asyncio
import time
from collections import OrderedDict, deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

Event = dict[str, Any]


@dataclass
class _Stream:
    events: deque[Event]
    seq: int = 0
    closed: bool = False
    subscribers: set[asyncio.Queue[Event | None]] = field(default_factory=set)


class EventBus:
    def __init__(self, max_events_per_stream: int = 2000, max_streams: int = 500) -> None:
        self._max_events = max_events_per_stream
        self._max_streams = max_streams
        self._streams: OrderedDict[str, _Stream] = OrderedDict()

    def has(self, stream_id: str) -> bool:
        return stream_id in self._streams

    def open(self, stream_id: str) -> None:
        if stream_id not in self._streams:
            self._streams[stream_id] = _Stream(events=deque(maxlen=self._max_events))
            self._evict()

    def publish(self, stream_id: str, event_type: str, data: dict[str, Any]) -> None:
        s = self._streams.get(stream_id)
        if s is None or s.closed:
            return
        s.seq += 1
        event: Event = {"seq": s.seq, "type": event_type, "ts": time.time(), "data": data}
        s.events.append(event)
        for q in s.subscribers:
            q.put_nowait(event)

    def close(self, stream_id: str) -> None:
        s = self._streams.get(stream_id)
        if s is None or s.closed:
            return
        s.closed = True
        for q in s.subscribers:
            q.put_nowait(None)
        self._evict()

    async def subscribe(self, stream_id: str, after_seq: int = 0) -> AsyncIterator[Event]:
        s = self._streams.get(stream_id)
        if s is None:
            return
        q: asyncio.Queue[Event | None] = asyncio.Queue()
        backlog = [e for e in s.events if e["seq"] > after_seq]
        last = backlog[-1]["seq"] if backlog else after_seq
        if not s.closed:
            s.subscribers.add(q)
        try:
            for e in backlog:
                yield e
            if s.closed:
                return
            while True:
                item = await q.get()
                if item is None:
                    return
                if item["seq"] > last:
                    last = item["seq"]
                    yield item
        finally:
            s.subscribers.discard(q)

    def _evict(self) -> None:
        if len(self._streams) <= self._max_streams:
            return
        for sid in [k for k, v in self._streams.items() if v.closed]:
            if len(self._streams) <= self._max_streams:
                break
            del self._streams[sid]
