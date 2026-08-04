"""In-process async pub/sub bus bridging the (sync, threaded) graph run and the
change-stream watcher to Server-Sent-Events subscribers.

publish() is thread-safe: worker threads schedule fan-out onto the API event
loop via call_soon_threadsafe. Each subscriber gets a bounded queue; slow
clients drop the oldest events rather than back-pressuring the producer.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any


class EventBus:
    def __init__(self, maxsize: int = 1000) -> None:
        self._subs: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._maxsize = maxsize

    def bind_loop(self) -> None:
        self._loop = asyncio.get_running_loop()

    def publish(self, event: dict[str, Any]) -> None:
        """Callable from any thread."""
        loop = self._loop
        if loop is None:
            return
        loop.call_soon_threadsafe(self._fanout, event)

    def _fanout(self, event: dict[str, Any]) -> None:
        for q in list(self._subs):
            if q.full():
                try:
                    q.get_nowait()
                except Exception:
                    pass
            try:
                q.put_nowait(event)
            except Exception:
                pass

    async def subscribe(self):
        q: asyncio.Queue = asyncio.Queue(maxsize=self._maxsize)
        self._subs.add(q)
        try:
            # greet so the client sees an open stream immediately
            yield {"type": "hello", "ts": _now_ms()}
            while True:
                event = await q.get()
                yield event
        finally:
            self._subs.discard(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)


def sse_format(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


def _now_ms() -> int:
    import time
    return int(time.time() * 1000)


bus = EventBus()
