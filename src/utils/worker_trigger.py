import os
import httpx

WORKER_SERVICE_URL = os.getenv("WORKER_SERVICE_URL", "")

async def trigger_worker():
    if not WORKER_SERVICE_URL:
        print("WORKER_SERVICE_URL not set — skipping worker trigger")
        return
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            await client.get(f"{WORKER_SERVICE_URL}/health")
    except Exception as e:
        print(f"Worker trigger failed (job still queued): {e}")