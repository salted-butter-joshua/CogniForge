"""Broadcast learn_loop logs to SSE subscribers."""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any


class RunEventBus:
    """Thread-safe pub/sub for a single run (logs + metrics)."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._closed = False

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=2000)
        with self._lock:
            if not self._closed:
                self._subscribers.append(q)
        return q

    def publish(self, event: dict[str, Any]) -> None:
        payload = {**event, "run_id": self.run_id, "ts": event.get("ts", time.time())}
        with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(payload)
            except queue.Full:
                try:
                    q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    pass

    def close(self, final: dict[str, Any] | None = None) -> None:
        with self._lock:
            self._closed = True
            subs = list(self._subscribers)
        if final:
            self.publish({**final, "type": "run_end"})
        for q in subs:
            try:
                q.put_nowait({"type": "_eof"})
            except queue.Full:
                pass


class BroadcastLogHandler(logging.Handler):
    def __init__(self, bus: RunEventBus) -> None:
        super().__init__()
        self.bus = bus

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.bus.publish(
                {
                    "type": "log",
                    "level": record.levelname,
                    "message": record.getMessage(),
                    "logger": record.name,
                    "ts": record.created,
                }
            )
        except Exception:
            self.handleError(record)


def attach_broadcast_handler(bus: RunEventBus) -> BroadcastLogHandler:
    handler = BroadcastLogHandler(bus)
    handler.setLevel(logging.DEBUG)
    logger = logging.getLogger("learn_loop")
    logger.addHandler(handler)
    return handler


def detach_broadcast_handler(handler: BroadcastLogHandler) -> None:
    logging.getLogger("learn_loop").removeHandler(handler)
