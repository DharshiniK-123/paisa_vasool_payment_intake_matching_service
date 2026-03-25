import json
from datetime import date, datetime
from decimal import Decimal

PREVIEW_TTL = 600
JOB_TTL = 3600


class _SafeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        return super().default(obj)


def _dumps(obj) -> str:
    return json.dumps(obj, cls=_SafeEncoder)


async def safe_redis_setex(key: str, ttl: int, value: str, redis_client=None):
    """
    Write a key to Redis. Accepts an explicit redis_client so that callers
    running inside a worker-created event loop can pass a freshly created
    client that is bound to the correct loop.
    """
    try:
        if redis_client is None:
            from src.data.clients.redis_clients import get_async_redis_client
            redis_client = get_async_redis_client()

        await redis_client.setex(key, ttl, value)
    except Exception as e:
        print(f"Redis error for key {key}: {str(e)}")
        raise


async def process_document_task(
    document_id: int,
    storage_path: str,
    file_type: str,
    file_url: str,
    document_type: str,
    job_id: str,
    redis_client=None,
) -> None:
    from src.core.services.document import extract_document_data

    await safe_redis_setex(
        f"job:{job_id}",
        JOB_TTL,
        _dumps({"status": "PROCESSING", "document_id": document_id}),
        redis_client=redis_client,
    )

    try:
        extracted_records = await extract_document_data(
            document_id=document_id,
            storage_path=storage_path,
            file_type=file_type,
            file_url=file_url,
            document_type=document_type,
        )

        await safe_redis_setex(
            f"preview:{document_id}",
            PREVIEW_TTL,
            _dumps(extracted_records),
            redis_client=redis_client,
        )

        await safe_redis_setex(
            f"job:{job_id}",
            JOB_TTL,
            _dumps(
                {
                    "status": "EXTRACTED",
                    "document_id": document_id,
                    "records_count": len(extracted_records),
                    "preview_data": extracted_records,
                }
            ),
            redis_client=redis_client,
        )

    except Exception as exc:
        error_detail = getattr(exc, "detail", str(exc))
        await safe_redis_setex(
            f"job:{job_id}",
            JOB_TTL,
            _dumps(
                {
                    "status": "FAILED",
                    "document_id": document_id,
                    "error": error_detail,
                }
            ),
            redis_client=redis_client,
        )
        raise


def process_document_task_sync(
    document_id: int,
    storage_path: str,
    file_type: str,
    file_url: str,
    document_type: str,
    job_id: str,
) -> None:
    import asyncio

    from src.data.clients.redis_clients import get_async_redis_client

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    redis_client = get_async_redis_client()

    try:
        loop.run_until_complete(
            process_document_task(
                document_id=document_id,
                storage_path=storage_path,
                file_type=file_type,
                file_url=file_url,
                document_type=document_type,
                job_id=job_id,
                redis_client=redis_client,
            )
        )
    except Exception:
        raise
    finally:
        try:
            loop.run_until_complete(redis_client.aclose())
        except Exception:
            pass
        loop.close()