from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict


@dataclass
class RateLimitResult:
    allowed: bool
    retry_after_sec: int = 0


class InMemoryRateLimiter:
    def __init__(self):
        self._events: Dict[str, Deque[float]] = defaultdict(deque)
        self._cooldown_until: Dict[str, float] = {}

    def check(self, key: str, limit: int, per_seconds: int) -> RateLimitResult:
        now = time.time()
        dq = self._events[key]
        cutoff = now - per_seconds
        while dq and dq[0] <= cutoff:
            dq.popleft()
        if len(dq) >= limit:
            retry = max(1, int(per_seconds - (now - dq[0])))
            return RateLimitResult(allowed=False, retry_after_sec=retry)
        dq.append(now)
        return RateLimitResult(allowed=True)

    def check_cooldown(self, key: str, cooldown_seconds: int) -> RateLimitResult:
        now = time.time()
        until = self._cooldown_until.get(key, 0)
        if until > now:
            return RateLimitResult(allowed=False, retry_after_sec=max(1, int(until - now)))
        self._cooldown_until[key] = now + cooldown_seconds
        return RateLimitResult(allowed=True)
