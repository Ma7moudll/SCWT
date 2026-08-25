"""JWT revocation by `jti`.

Every access token carries a unique `jti`. Logout records the jti until the
token's natural expiry; authentication rejects revoked jtis. The store is an
in-memory TTL map — process-local, which is exactly the lifetime a revocation
needs when tokens are verified only by this process. The `RevocationStore`
protocol keeps call sites stable for a future Redis implementation.
"""
from __future__ import annotations

import threading
import time


class RevocationStore:
    def __init__(self) -> None:
        self._revoked: dict[str, float] = {}
        self._lock = threading.Lock()

    def revoke(self, jti: str, ttl_seconds: float) -> None:
        """Revokes `jti` for the remaining token lifetime."""
        if not jti or ttl_seconds <= 0:
            return
        with self._lock:
            self._revoked[jti] = time.monotonic() + ttl_seconds
            self._prune_locked()

    def is_revoked(self, jti: str) -> bool:
        if not jti:
            return False
        with self._lock:
            expiry = self._revoked.get(jti)
            if expiry is None:
                return False
            if expiry < time.monotonic():
                del self._revoked[jti]
                return False
            return True

    def _prune_locked(self) -> None:
        now = time.monotonic()
        expired = [j for j, exp in self._revoked.items() if exp < now]
        for j in expired:
            del self._revoked[j]

    def reset(self) -> None:
        with self._lock:
            self._revoked.clear()


revocations = RevocationStore()
