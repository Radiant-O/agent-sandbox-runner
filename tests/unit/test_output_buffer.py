from app.sandbox.output import OutputBuffer


def test_buffer_under_limit_keeps_all() -> None:
    b = OutputBuffer(100)
    b.append("hello ")
    b.append("world")
    assert b.text == "hello world"
    assert b.truncated is False


def test_buffer_truncates_and_flags() -> None:
    b = OutputBuffer(10)
    b.append("a" * 25)
    assert len(b.text.encode()) == 10
    assert b.truncated is True


def test_buffer_never_splits_multibyte_char() -> None:
    b = OutputBuffer(5)
    b.append("ééé")  # 6 bytes
    assert b.text == "éé"
    assert len(b.text.encode()) <= 5
    assert b.truncated is True


def test_buffer_ignores_chunks_after_full() -> None:
    b = OutputBuffer(1024)
    chunk = "x" * 1024
    for _ in range(10_000):
        b.append(chunk)
    assert len(b.text.encode()) == 1024
    assert b.truncated is True
