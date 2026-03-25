from __future__ import annotations

import logging

import redis
import redis.asyncio as aioredis

from src.config.settings import settings

logger = logging.getLogger(__name__)

try:
    redis_client: aioredis.Redis | None = aioredis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=30,
    )
except Exception:
    logger.warning("redis_client unavailable — async Redis could not be initialised")
    redis_client = None

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
