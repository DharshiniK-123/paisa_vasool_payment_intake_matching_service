from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.rest.routes import aged_router, document_routes, matching_router
from src.api.websocket.aging_ws import router as aging_ws_router
from src.core.services.scheduler import JOB_ID, scheduler, start_scheduler_from_db, stop_scheduler
from src.observability.logging import setup_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup_begin")
    setup_logging()
    await start_scheduler_from_db()
    logger.info("scheduler_started")
    yield
    stop_scheduler()
    logger.info("shutdown_complete")


app = FastAPI(title="Payment intake and matching service", lifespan=lifespan)

app.include_router(document_routes.router, prefix="/api/v1/payment_intake_matching")
app.include_router(matching_router.router, prefix="/api/v1/payment_intake_matching")
app.include_router(aged_router.router, prefix="/api/v1/payment_intake_matching")
app.include_router(aging_ws_router)


@app.get("/api/v1/payment_intake_matching/scheduler/status")
async def scheduler_status():
    job = scheduler.get_job(JOB_ID)
    return {
        "scheduler_running": scheduler.running,
        "job_exists": job is not None,
        "next_run": str(job.next_run_time) if job else None,
        "job_id": JOB_ID,
    }
