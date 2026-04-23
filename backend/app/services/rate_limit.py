from __future__ import annotations

from dataclasses import dataclass

from redis import Redis


@dataclass(slots=True)
class RateLimitResult:
    allowed: bool
    remaining: int


class GenerationRateLimiter:
    def __init__(self, redis_client: Redis, limit: int, window_seconds: int) -> None:
        self.redis_client = redis_client
        self.limit = limit
        self.window_seconds = window_seconds

    def check(self, identity: str) -> RateLimitResult:
        key = f"rate_limit:generation:{identity}"
        count = self.redis_client.incr(key)
        if count == 1:
            self.redis_client.expire(key, self.window_seconds)
        remaining = max(self.limit - count, 0)
        return RateLimitResult(allowed=count <= self.limit, remaining=remaining)
