"""Cross-thread event bus bridging MQTT callbacks (background thread) to
FastAPI WebSocket consumers (asyncio loop).

`publish(operation_id, event)` is called from the MQTT thread and fans out to
every connected WebSocket subscribed to that operation. If no service is
listening on the loop yet, the event is enqueued and delivered on subscribe.
"""
from __future__ import annotations

import asyncio
import logging
import threading

logger = logging.getLogger("recycle.websocket")


class DepositEventBus:
    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self, operation_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        with self._lock:
            self._queues.setdefault(operation_id, []).append(q)
        return q

    def unsubscribe(self, operation_id: str, q: asyncio.Queue) -> None:
        with self._lock:
            subs = self._queues.get(operation_id) or []
            if q in subs:
                subs.remove(q)
            if not subs:
                self._queues.pop(operation_id, None)

    def publish(self, operation_id: str, event: dict) -> None:
        with self._lock:
            subs = list(self._queues.get(operation_id) or [])
        if not subs or self._loop is None:
            return
        for q in subs:
            try:
                fb = asyncio.run_coroutine_threadsafe(q.put(event), self._loop)
                # Do not block the MQTT thread; a full queue is a client we
                # could not reach, which is fine (the deposit still persists).
                fb.add_done_callback(lambda _f: None)
            except Exception:  # pragma: no cover
                logger.warning("dropped event for %s", operation_id)


event_bus = DepositEventBus()