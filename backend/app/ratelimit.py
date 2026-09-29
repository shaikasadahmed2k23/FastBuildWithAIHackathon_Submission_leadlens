"""In-memory sliding-window rate limiter for the LLM-backed endpoints.

Per process only; enough for a single API instance. Behind a proxy, run uvicorn with
``--proxy-headers`` so the client address is the real caller, not the proxy.
"""

import threading
import time
from collections import defaultdict, deque

WINDOW_S = 60.0


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, now: float | None = None) -> float | None:
        """Record a hit. Returns seconds to wait if ``key`` is over ``limit`` per minute, else None."""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= WINDOW_S:
                hits.popleft()
            if len(hits) >= limit:
                return WINDOW_S - (now - hits[0])
            hits.append(now)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = RateLimiter()
