"""Sliding-window rate limiter for authentication endpoints.

In-memory per-process implementation: correct for the single-process
prototype deployment. The `RateLimiter` protocol keeps the call sites stable
so a Redis-backed limiter can replace it without touching the routers.

Keyed by "identity" — the client IP (proxy-aware via X-Forwarded-For when the
request came through one). Never logs or stores anything beyond counters.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Protocol


class RateLimiter(Protocol):
    def hit(self, key: str) -> bool:
        """Records one attempt; True if allowed, False if over the limit."""
        ...


class MemoryRateLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            while bucket and now - bucket[0] > self.window:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def client_identity(request) -> str:
    """Best-effort client identity for rate limiting.

    Uses the first X-Forwarded-For hop when present (the deployment sits
    behind a trusted proxy in production), else the socket peer."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return f"fwd:{forwarded.split(',')[0].strip()}"
    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"
