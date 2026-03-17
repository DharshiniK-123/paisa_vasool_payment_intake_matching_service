import asyncio
import json
from datetime import date, datetime
from decimal import Decimal

from src.data.clients.redis_clients import redis_client

PREVIEW_TTL = 600
JOB_TTL     = 3600


# FIX #5 — custom encoder so date / Decimal values from pandas don't crash
#           json.dumps (which only handles str/int/float/list/dict/bool/None)
class _SafeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, (date, datetime)):
            return obj.isoformat()
        return super().default(obj)


def _dumps(obj) -> str:
    return json.dumps(obj, cls=_SafeEncoder)


def process_document_task(
    document_id: int,
    storage_path: str,
    file_type: str,
    file_url: str,
    document_type: str,
    job_id: str,
) -> None:
    from src.core.services.document import extract_document_data

    redis_client.setex(
        f"job:{job_id}",
        JOB_TTL,
        _dumps({"status": "PROCESSING", "document_id": document_id}),
    )

    try:
        extracted_records = asyncio.run(
            extract_document_data(
                document_id=document_id,
                storage_path=storage_path,
                file_type=file_type,
                file_url=file_url,
                document_type=document_type,
            )
        )

        redis_client.setex(
            f"preview:{document_id}",
            PREVIEW_TTL,
            _dumps(extracted_records),
        )
        redis_client.setex(
            f"job:{job_id}",
            JOB_TTL,
            _dumps({
                "status":        "EXTRACTED",
                "document_id":   document_id,
                "records_count": len(extracted_records),
                "preview_data":  extracted_records,
            }),
        )

    except Exception as exc:
        error_detail = getattr(exc, "detail", str(exc))
        redis_client.setex(
            f"job:{job_id}",
            JOB_TTL,
            _dumps({
                "status":      "FAILED",
                "document_id": document_id,
                "error":       error_detail,
            }),
        )
        raise
