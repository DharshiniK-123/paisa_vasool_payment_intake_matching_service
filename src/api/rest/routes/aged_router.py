from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rest.dependencies import get_db
from src.core.services import aged_service as service
from src.core.services.scheduler import reschedule_aging_job, run_aging_and_reminders
from src.schemas.payment_intake_matching import (
    AgingConfigCreate,
    AgingConfigResponse,
    AgingConfigUpdate,
    ReminderLogResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Aging & Reminders"])


@router.post("/aging/run")
async def trigger_aging_job():
    """Trigger aging jobs"""
    try:
        await run_aging_and_reminders()
        return {"status": "Aging job completed successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Aging job failed: {str(e)}") from e


@router.get("/scheduler/settings")
async def get_scheduler_settings(db: AsyncSession = Depends(get_db)):
    """To fetch the scheduler settings"""
    try:
        return await service.get_scheduler(db)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Could not fetch scheduler settings.") from e


@router.put("/scheduler/settings")
async def update_scheduler_settings(
    run_hour: int,
    run_minute: int,
    is_enabled: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """update scheduler settings"""
    try:
        result = await service.update_scheduler(run_hour, run_minute, is_enabled, db)
        if result["is_enabled"]:
            await reschedule_aging_job(result["utc_hour"], result["utc_minute"])
        return {
            "status": result["status"],
            "run_hour": result["run_hour"],
            "run_minute": result["run_minute"],
            "is_enabled": result["is_enabled"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail="Could not update scheduler settings.") from e


@router.get("/aging-config/", response_model=list[AgingConfigResponse])
async def get_all_configs(db: AsyncSession = Depends(get_db)):
    """fetch all the aging buckets like low medium high"""
    try:
        return await service.list_configs(db)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Could not fetch aging configs.") from e


@router.get("/aging-config/{config_id}", response_model=AgingConfigResponse)
async def get_config(config_id: int, db: AsyncSession = Depends(get_db)):
    """fetch a single aging config bucket"""
    try:
        config = await service.get_config(config_id, db)
        if not config:
            raise HTTPException(status_code=404, detail=f"Aging config {config_id} not found.")
        return config
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Could not fetch aging config.") from e


@router.post("/aging-config/", response_model=AgingConfigResponse)
async def create_config(payload: AgingConfigCreate, db: AsyncSession = Depends(get_db)):
    """Add new aging config like from to and the bucket(low/medium/high)"""
    from sqlalchemy.exc import IntegrityError

    try:
        return await service.create_config(payload, db)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail=f"A config with severity '{payload.severity}' already exists."
        ) from e
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Could not create aging config: {str(e)}"
        ) from e


@router.put("/aging-config/{config_id}", response_model=AgingConfigResponse)
async def update_config(
    config_id: int, payload: AgingConfigUpdate, db: AsyncSession = Depends(get_db)
):
    try:
        """update the aging config"""
        config = await service.update_config(config_id, payload, db)
        if not config:
            raise HTTPException(status_code=404, detail=f"Aging config {config_id} not found.")
        return config
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Could not update aging config: {str(e)}"
        ) from e


@router.delete("/aging-config/{config_id}")
async def delete_config(config_id: int, db: AsyncSession = Depends(get_db)):
    try:
        """delete the configured data for aged reminders"""
        deleted = await service.delete_config(config_id, db)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Aging config {config_id} not found.")
        return {"status": "Deleted successfully."}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Could not delete aging config: {str(e)}"
        ) from e


@router.get("/aging/reminders", response_model=list[ReminderLogResponse])
async def get_all_reminders(db: AsyncSession = Depends(get_db)):
    """fetch all the reminders sent to customer for overdue"""
    try:
        return await service.list_reminders(db)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Could not fetch reminders.") from e
