"""Small in-process sliding-window rate limiter.

Good enough for a single backend process. With several workers or hosts, back this with Redis.
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request

from .auth import current_user
from .models import User

_lock = threading.Lock()
_hits: dict[tuple, deque] = defaultdict(deque)


def check(key: tuple, limit: int, window_s: float) -> None:
    now = time.monotonic()
    with _lock:
        q = _hits[key]
        while q and now - q[0] > window_s:
            q.popleft()
        if len(q) >= limit:
            retry = int(window_s - (now - q[0])) + 1
            raise HTTPException(429, f"Too many requests. Try again in {retry}s.", headers={"Retry-After": str(retry)})
        q.append(now)


def reset() -> None:
    with _lock:
        _hits.clear()


def per_user(bucket: str, limit: int, window_s: float = 60):
    """Dependency: limit an authenticated endpoint per user."""

    def dep(user: User = Depends(current_user)) -> User:
        check(("user", user.id, bucket), limit, window_s)
        return user

    return dep


def per_ip(bucket: str, limit: int, window_s: float = 60):
    def dep(request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        check(("ip", ip, bucket), limit, window_s)

    return dep
