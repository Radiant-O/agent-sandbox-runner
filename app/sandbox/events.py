"""Lifecycle event emission for sandbox backends.

Backends call `emit(...)` at each real lifecycle step. Whoever is running the code
(the execution service, the agent) installs a sink with `sink_scope`; with no sink,
emitting is a no-op. Context-local, like the logging correlation ids.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

EventSink = Callable[[str, dict[str, Any]], None]

_current_sink: ContextVar[EventSink | None] = ContextVar("event_sink", default=None)


def emit(event_type: str, **data: Any) -> None:
    sink = _current_sink.get()
    if sink is not None:
        sink(event_type, data)


def current_sink() -> EventSink | None:
    return _current_sink.get()


@contextmanager
def sink_scope(sink: EventSink) -> Iterator[None]:
    token = _current_sink.set(sink)
    try:
        yield
    finally:
        _current_sink.reset(token)
