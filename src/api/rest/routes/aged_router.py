from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from src.api.rest.dependencies import get_db
from src.core.services.scheduler import run_aging_and_reminders, reschedule_aging_job
from src.data.models.postgres.reminder_log import ReminderLog
from src.data.models.postgres.aging_config import AgingConfig
from src.schemas.payment_intake_matching import (AgingConfigCreate,AgingConfigUpdate,AgingConfigResponse,ReminderLogResponse,)

router = APIRouter(tags=["Aging & Reminders"])

@router.post("/aging/run")
async def trigger_aging_job():
    try:
        await run_aging_and_reminders()
        return {"status": "Aging job completed successfully."}
    except Exception:
        raise HTTPException(status_code=500, detail="Aging job failed. Please try again.")
    
@router.get("/aging-config/", response_model=list[AgingConfigResponse])
async def get_all_configs(db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(select(AgingConfig).order_by(AgingConfig.id.asc()))
        return result.scalars().all()
    except Exception:
        raise HTTPException(status_code=500, detail="Could not fetch aging configs. Please try again.")


@router.get("/aging-config/{config_id}", response_model=AgingConfigResponse)
async def get_config(config_id: int, db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(select(AgingConfig).where(AgingConfig.id == config_id))
        config = result.scalar_one_or_none()
        if not config:
            raise HTTPException(status_code=404, detail=f"Aging config {config_id} not found.")
        return config
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Could not fetch aging config. Please try again.")

@router.get("/aging/reminders", response_model=list[ReminderLogResponse])
async def get_all_reminders(db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(select(ReminderLog).order_by(ReminderLog.sent_at.desc()))
        return result.scalars().all()
    except Exception:
        raise HTTPException(status_code=500, detail="Could not fetch reminders. Please try again.")


@router.post("/aging-config/", response_model=AgingConfigResponse)
async def create_config(payload: AgingConfigCreate, db: AsyncSession = Depends(get_db)):
    try:
        config = AgingConfig(**payload.model_dump())
        db.add(config)
        await db.commit()
        await db.refresh(config)
        if config.severity == "SCHEDULER" and config.run_hour is not None:
            await reschedule_aging_job(config.run_hour, config.run_minute or 0)
        return config
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Could not create aging config. Please try again.")


@router.put("/aging-config/{config_id}", response_model=AgingConfigResponse)
async def update_config(config_id: int, payload: AgingConfigUpdate, db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(select(AgingConfig).where(AgingConfig.id == config_id))
        config = result.scalar_one_or_none()
        if not config:
            raise HTTPException(status_code=404, detail=f"Aging config {config_id} not found.")
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(config, key, value)
        await db.commit()
        await db.refresh(config)
        if config.severity == "SCHEDULER" and config.run_hour is not None:
            await reschedule_aging_job(config.run_hour, config.run_minute or 0)
        return config
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Could not update aging config. Please try again.")


@router.delete("/aging-config/{config_id}")
async def delete_config(config_id: int, db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(select(AgingConfig).where(AgingConfig.id == config_id))
        config = result.scalar_one_or_none()
        if not config:
            raise HTTPException(status_code=404, detail=f"Aging config {config_id} not found.")
        await db.delete(config)
        await db.commit()
        return {"status": "Deleted successfully."}
    except HTTPException:
        raise
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Could not delete aging config. Please try again.")