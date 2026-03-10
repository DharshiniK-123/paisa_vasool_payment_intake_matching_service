import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from src.api.rest.dependencies import get_db
from src.core.services.scheduler import run_aging_and_reminders, reschedule_aging_job
from src.data.models.postgres.reminder_log import ReminderLog
from src.data.models.postgres.aging_config import AgingConfig
from src.data.models.postgres.scheduler_settings import SchedulerSettings
from src.schemas.payment_intake_matching import (
    AgingConfigCreate, AgingConfigUpdate, AgingConfigResponse, ReminderLogResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Aging & Reminders"])


@router.post("/aging/run")
async def trigger_aging_job():
    try:
        await run_aging_and_reminders()
        return {"status": "Aging job completed successfully."}
    except Exception as e:
        logger.error("Aging job failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Aging job failed: {str(e)}")


def _ist_to_utc(hour: int, minute: int):
    total_minutes = hour * 60 + minute - 330  
    total_minutes = total_minutes % (24 * 60)
    return total_minutes // 60, total_minutes % 60


def _utc_to_ist(hour: int, minute: int):
    total_minutes = hour * 60 + minute + 330 
    total_minutes = total_minutes % (24 * 60)  
    return total_minutes // 60, total_minutes % 60


@router.get("/scheduler/settings")
async def get_scheduler_settings(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SchedulerSettings).where(SchedulerSettings.id == 1))
    row = result.scalar_one_or_none()
    utc_hour   = row.run_hour   if row else 9
    utc_minute = row.run_minute if row else 0
    ist_hour, ist_minute = _utc_to_ist(utc_hour, utc_minute)
    return {
        "run_hour":   ist_hour,
        "run_minute": ist_minute,
        "is_enabled": row.is_enabled if row else False,
    }


@router.put("/scheduler/settings")
async def update_scheduler_settings(run_hour: int,run_minute: int,is_enabled: bool = True,db: AsyncSession = Depends(get_db),):
    utc_hour, utc_minute = _ist_to_utc(run_hour, run_minute)
    print(f"[SCHEDULER] Saving IST {run_hour:02d}:{run_minute:02d} → UTC {utc_hour:02d}:{utc_minute:02d}")
    result = await db.execute(select(SchedulerSettings).where(SchedulerSettings.id == 1))
    row = result.scalar_one_or_none()
    if row is None:
        row = SchedulerSettings(id=1, run_hour=utc_hour, run_minute=utc_minute, is_enabled=is_enabled)
        db.add(row)
    else:
        row.run_hour   = utc_hour
        row.run_minute = utc_minute
        row.is_enabled = is_enabled
    await db.commit()

    if is_enabled:
        await reschedule_aging_job(utc_hour, utc_minute)

    return {
        "status":     "Scheduler updated",
        "run_hour":   run_hour,    
        "run_minute": run_minute,
        "is_enabled": is_enabled,
    }


@router.get("/aging-config/", response_model=list[AgingConfigResponse])
async def get_all_configs(db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(
            select(AgingConfig)
            .where(AgingConfig.severity != "SCHEDULER")  
            .order_by(AgingConfig.id.asc())
        )
        return result.scalars().all()
    except Exception as e:
        logger.error("get_all_configs failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not fetch aging configs.")


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
    except Exception as e:
        logger.error("get_config failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not fetch aging config.")


@router.post("/aging-config/", response_model=AgingConfigResponse)
async def create_config(payload: AgingConfigCreate, db: AsyncSession = Depends(get_db)):
    try:
        existing = await db.execute(
            select(AgingConfig).where(AgingConfig.severity == payload.severity)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail=f"An aging config with severity '{payload.severity}' already exists. Use PUT to update it.",
            )
        data = payload.model_dump(exclude={"run_hour", "run_minute", "message_template"})
        config = AgingConfig(**data)
        db.add(config)
        await db.commit()
        await db.refresh(config)
        return config

    except HTTPException:
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.error("create_config integrity error: %s", e, exc_info=True)
        raise HTTPException(
            status_code=409,
            detail=f"A config with severity '{payload.severity}' already exists.",
        )
    except Exception as e:
        await db.rollback()
        logger.error("create_config failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Could not create aging config: {str(e)}")


@router.put("/aging-config/{config_id}", response_model=AgingConfigResponse)
async def update_config(config_id: int, payload: AgingConfigUpdate, db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(select(AgingConfig).where(AgingConfig.id == config_id))
        config = result.scalar_one_or_none()
        if not config:
            raise HTTPException(status_code=404, detail=f"Aging config {config_id} not found.")

        for key, value in payload.model_dump(exclude_unset=True, exclude={"run_hour", "run_minute"}).items():
            setattr(config, key, value)

        await db.commit()
        await db.refresh(config)
        return config

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error("update_config failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Could not update aging config: {str(e)}")


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
    except Exception as e:
        await db.rollback()
        logger.error("delete_config failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Could not delete aging config: {str(e)}")


@router.get("/aging/reminders", response_model=list[ReminderLogResponse])
async def get_all_reminders(db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(select(ReminderLog).order_by(ReminderLog.sent_at.desc()))
        return result.scalars().all()
    except Exception as e:
        logger.error("get_all_reminders failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not fetch reminders.")