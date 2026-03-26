from __future__ import annotations

import logging

import redis

from src.config.settings import settings

logger = logging.getLogger(__name__)


try:
    redis_connection: redis.Redis | None = redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        socket_connect_timeout=3,
        socket_timeout=30,
    )
    assert redis_connection is not None
    redis_connection.ping()
except Exception:
    logger.warning("redis_connection unavailable — sync Redis (RQ) could not be initialised")
    redis_connection = None


def get_async_redis_client():
    """
    Create a fresh async Redis client bound to the current event loop.
    Always call this inside an async function — never at module level.
    """
    import redis.asyncio as aioredis

    return aioredis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=30,
    )