from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from src.core.services.scheduler import start_scheduler_from_db, stop_scheduler, scheduler, JOB_ID
from src.api.rest.routes import matching_router
from src.data.clients.postgres_client import init_db
from src.api.rest.routes import document_routes
from src.api.rest.routes import aged_router
from src.data.models.postgres import scheduler_settings 


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Init db inialized")
    await init_db()
    print("scheduler initilized")
    await start_scheduler_from_db()
    yield
    stop_scheduler()


app = FastAPI(title="payment intake and matching service", lifespan=lifespan)

app.include_router(document_routes.router, prefix="/api/v1/payment_intake_matching")
app.include_router(matching_router.router, prefix="/api/v1/payment_intake_matching")
app.include_router(aged_router.router, prefix="/api/v1/payment_intake_matching")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")


@app.get("/api/v1/payment_intake_matching/scheduler/status")
async def scheduler_status():
    job = scheduler.get_job(JOB_ID)
    return {
        "scheduler_running": scheduler.running,
        "job_exists":        job is not None,
        "next_run":          str(job.next_run_time) if job else None,
        "job_id":            JOB_ID,
    }
