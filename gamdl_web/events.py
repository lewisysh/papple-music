from __future__ import annotations

import asyncio
import json
from typing import Any


class EventBus:
    """Fan-out of server events to every connected SSE client."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def publish(self, event: str, data: Any) -> None:
        # gamdl logs from worker threads too (asyncio.to_thread), so hop back
        # onto the event loop before touching the queues.
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if self._loop is not None and running is not self._loop:
            self._loop.call_soon_threadsafe(self._publish, event, data)
        else:
            self._publish(event, data)

    def _publish(self, event: str, data: Any) -> None:
        message = format_sse(event, data)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # A stalled client; it will resync from the snapshot on reconnect.
                pass


def format_sse(event: str, data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n"
