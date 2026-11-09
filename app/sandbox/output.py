"""Byte-capped output capture. Protects the server from unbounded sandbox output."""


class OutputBuffer:
    def __init__(self, limit_bytes: int) -> None:
        self._limit = limit_bytes
        self._parts: list[bytes] = []
        self._size = 0
        self.truncated = False

    def append(self, chunk: str) -> None:
        if self.truncated:
            return
        data = chunk.encode("utf-8")
        room = self._limit - self._size
        if len(data) <= room:
            self._parts.append(data)
            self._size += len(data)
            return
        # Keep what fits, cut on a UTF-8 character boundary, drop everything after.
        cut = data[:room].decode("utf-8", errors="ignore").encode("utf-8")
        self._parts.append(cut)
        self._size += len(cut)
        self.truncated = True

    @property
    def text(self) -> str:
        return b"".join(self._parts).decode("utf-8", errors="replace")
