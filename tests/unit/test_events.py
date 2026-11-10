import asyncio

from app.sandbox.events import emit, sink_scope
from app.services.events import EventBus


async def _collect(bus: EventBus, stream_id: str, after: int = 0) -> list[dict[str, object]]:
    return [e async for e in bus.subscribe(stream_id, after_seq=after)]


async def test_late_subscriber_gets_replay_then_live() -> None:
    bus = EventBus()
    bus.open("s1")
    bus.publish("s1", "queued", {})
    bus.publish("s1", "stdout", {"data": "a"})

    task = asyncio.create_task(_collect(bus, "s1"))
    await asyncio.sleep(0)
    bus.publish("s1", "stdout", {"data": "b"})
    bus.close("s1")
    events = await asyncio.wait_for(task, 1)

    assert [e["type"] for e in events] == ["queued", "stdout", "stdout"]
    assert [e["seq"] for e in events] == [1, 2, 3]
    assert events[2]["data"] == {"data": "b"}


async def test_resume_after_seq() -> None:
    bus = EventBus()
    bus.open("s")
    for i in range(5):
        bus.publish("s", "tick", {"i": i})
    bus.close("s")
    events = await _collect(bus, "s", after=3)
    assert [e["seq"] for e in events] == [4, 5]


async def test_unknown_stream_yields_nothing() -> None:
    assert await _collect(EventBus(), "nope") == []


async def test_replay_buffer_is_bounded() -> None:
    bus = EventBus(max_events_per_stream=10)
    bus.open("s")
    for i in range(50):
        bus.publish("s", "tick", {"i": i})
    bus.close("s")
    events = await _collect(bus, "s")
    assert len(events) == 10
    assert events[-1]["seq"] == 50


async def test_closed_streams_are_evicted_beyond_capacity() -> None:
    bus = EventBus(max_streams=3)
    for i in range(5):
        bus.open(f"s{i}")
        bus.close(f"s{i}")
    assert bus.has("s4") and not bus.has("s0")


def test_emit_without_sink_is_noop() -> None:
    emit("anything", x=1)  # must not raise


def test_emit_goes_to_innermost_sink() -> None:
    seen: list[tuple[str, dict[str, object]]] = []
    with sink_scope(lambda t, d: seen.append((t, d))):
        emit("sandbox_created", create_ms=600)
    emit("after_scope")
    assert seen == [("sandbox_created", {"create_ms": 600})]
