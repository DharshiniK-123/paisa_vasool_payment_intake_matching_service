import os
import redis

REDIS_HOST = os.environ.get("REDIS_HOST", "10.125.46.155")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))

try:
    redis_client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        decode_responses=True,
        socket_connect_timeout=3,   
        socket_timeout=30,
    )
    redis_client.ping()
except Exception as e:
    redis_client = None

try:
    redis_connection = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        socket_connect_timeout=3,
        socket_timeout=30,
    )
    redis_connection.ping()
except Exception as e:
    redis_connection = None
