from __future__ import annotations

from redis import Redis

from app.core.config import get_settings


settings = get_settings()
redis_client = Redis.from_url(settings.redis_url)


def get_redis() -> Redis:
    return redis_client
