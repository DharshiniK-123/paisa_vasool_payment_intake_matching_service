from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from src.core.services.scheduler import start_scheduler_from_db
from src.api.rest.routes import matching_router
from src.data.clients.postgres_client import init_db
from src.api.rest.routes import document_routes
from src.api.rest.routes import aged_router

app = FastAPI(title="payment intake and matching service")

app.include_router(document_routes.router, prefix="/api/v1/payment_intake_matching")
app.include_router(matching_router.router, prefix="/api/v1/payment_intake_matching")
app.include_router(aged_router.router, prefix="/api/v1/payment_intake_matching")
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
@app.on_event("startup")
async def on_startup():
    await init_db()
    await start_scheduler_from_db()