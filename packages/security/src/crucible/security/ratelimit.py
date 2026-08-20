"""Redis fixed-window rate limiting.

Expensive routes (upload creation, run creation) must **fail closed**: if the
limiter itself is unavailable we refuse rather than admit unbounded work
(plan §5.5, "Fail closed for expensive execution routes"). The caller decides,
via `RateLimitDecision.limiter_available`, whether a route is cheap enough to
fail open.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    limit: int
    reset_seconds: int
    limiter_available: bool = True


class RedisRateLimiter:
    def __init__(self, client: Any, *, namespace: str = "rl") -> None:
        self._redis = client
        self._ns = namespace

    async def check(self, key: str, *, limit: int, window_seconds: int) -> RateLimitDecision:
        """Increment the window counter and report whether the call is allowed."""
        redis_key = f"{self._ns}:{key}:{window_seconds}"
        try:
            pipe = self._redis.pipeline()
            pipe.incr(redis_key)
            pipe.expire(redis_key, window_seconds, nx=True)
            pipe.ttl(redis_key)
            count, _, ttl = await pipe.execute()
        except Exception:
            return RateLimitDecision(
                allowed=False,
                remaining=0,
                limit=limit,
                reset_seconds=window_seconds,
                limiter_available=False,
            )
        count = int(count)
        ttl = int(ttl) if int(ttl) > 0 else window_seconds
        return RateLimitDecision(
            allowed=count <= limit,
            remaining=max(0, limit - count),
            limit=limit,
            reset_seconds=ttl,
        )
