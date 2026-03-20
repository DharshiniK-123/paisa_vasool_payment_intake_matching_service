import json
from datetime import date, datetime
from decimal import Decimal

PREVIEW_TTL = 600
JOB_TTL     = 3600


class _SafeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        return super().default(obj)


def _dumps(obj) -> str:
    return json.dumps(obj, cls=_SafeEncoder)


def safe_redis_setex(key: str, ttl: int, value: str):
    try:
        from src.data.clients.redis_clients import redis_client  
        if redis_client:
            redis_client.setex(key, ttl, value)
        else:
            print("Redis client not available — skipping cache")
    except Exception as e:
        print(f"Redis error for key {key}: {str(e)}")
        raise

async def process_document_task(document_id: int,storage_path: str,file_type: str,file_url: str,document_type: str,job_id: str,) -> None:
   
    from src.core.services.document import extract_document_data  # lazy import

    safe_redis_setex(
        f"job:{job_id}",
        JOB_TTL,
        _dumps({
            "status": "PROCESSING",
            "document_id": document_id
        }),
    )

    try:
        extracted_records = await extract_document_data(
            document_id=document_id,
            storage_path=storage_path,
            file_type=file_type,
            file_url=file_url,
            document_type=document_type,
        )

     
        safe_redis_setex(
            f"preview:{document_id}",
            PREVIEW_TTL,
            _dumps(extracted_records),
        )

        safe_redis_setex(
            f"job:{job_id}",
            JOB_TTL,
            _dumps({
                "status": "EXTRACTED",
                "document_id": document_id,
                "records_count": len(extracted_records),
                "preview_data": extracted_records,
            }),
        )

    except Exception as exc:
        error_detail = getattr(exc, "detail", str(exc))
        safe_redis_setex(
            f"job:{job_id}",
            JOB_TTL,
            _dumps({
                "status": "FAILED",
                "document_id": document_id,
                "error": error_detail,
            }),
        )
        raise

def process_document_task_sync(document_id: int,storage_path: str,file_type: str,file_url: str,document_type: str,job_id: str,) -> None:
    
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(process_document_task(
            document_id=document_id,
            storage_path=storage_path,
            file_type=file_type,
            file_url=file_url,
            document_type=document_type,
            job_id=job_id,
        ))
    except Exception as e:
        raise
    finally:
        loop.close()