from datetime import date
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.aging_config import AgingConfig
from src.data.repositories import aging_repository as repo
from src.schemas.payment_intake_matching import (
    AgingConfigCreate,
    AgingConfigUpdate,
    ReminderLogResponse,
)


def ist_to_utc(hour: int, minute: int) -> tuple[int, int]:
    total = hour * 60 + minute - 330
    total = total % (24 * 60)
    return total // 60, total % 60


def utc_to_ist(hour: int, minute: int) -> tuple[int, int]:
    total = hour * 60 + minute + 330
    total = total % (24 * 60)
    return total // 60, total % 60



def calculate_days_overdue(due_date: date) -> int:
    return (date.today() - due_date).days


def assign_aging_bucket(days_overdue: int, configs: list[AgingConfig]) -> AgingConfig | None:
    if days_overdue <= 0:
        return None
    for config in configs:
        if config.due_days_to is None:
            if days_overdue >= config.due_days_from:
                return config
        else:
            if config.due_days_from <= days_overdue <= config.due_days_to:
                return config
    return None


async def get_overdue_invoices_with_bucket(db: AsyncSession) -> list[dict]:
    invoices = await repo.get_overdue_invoices(db)
    configs = await repo.get_active_aging_configs(db)
    if not configs:
        return []

    result = []
    for invoice in invoices:
        days_overdue = calculate_days_overdue(cast(date, invoice.due_date))
        config = assign_aging_bucket(days_overdue, configs)
        if config is None:
            continue
        result.append({"invoice": invoice, "days_overdue": days_overdue, "config": config})
    return result


async def list_configs(db: AsyncSession) -> list[AgingConfig]:
    return await repo.get_all_aging_configs(db)


async def get_config(config_id: int, db: AsyncSession) -> AgingConfig | None:
    return await repo.get_aging_config_by_id(config_id, db)


async def create_config(payload: AgingConfigCreate, db: AsyncSession) -> AgingConfig:
    existing = await repo.get_aging_config_by_severity(payload.severity, db)
    if existing:
        raise ValueError(f"An aging config with severity '{payload.severity}' already exists.")
    data = payload.model_dump(exclude={"run_hour", "run_minute", "message_template"})
    return await repo.create_aging_config(db, data)


async def update_config(
        config_id: int, 
        payload: AgingConfigUpdate, 
        db: AsyncSession) -> AgingConfig | None:
    
    config = await repo.get_aging_config_by_id(config_id, db)
    if not config:
        return None
    updates = payload.model_dump(exclude_unset=True, exclude={"run_hour", "run_minute"})
    return await repo.update_aging_config(config, updates, db)


async def delete_config(config_id: int, db: AsyncSession) -> bool:
    config = await repo.get_aging_config_by_id(config_id, db)
    if not config:
        return False
    await repo.delete_aging_config(config, db)
    return True


async def get_scheduler(db: AsyncSession) -> dict:
    row = await repo.get_scheduler_settings(db)
    utc_hour = int(row.run_hour) if row else 9
    utc_minute = int(row.run_minute) if row else 0
    ist_hour, ist_minute = utc_to_ist(utc_hour, utc_minute)
    return {
        "run_hour": ist_hour,
        "run_minute": ist_minute,
        "is_enabled": row.is_enabled if row else False,
    }


async def update_scheduler(
    run_hour: int, run_minute: int, is_enabled: bool, db: AsyncSession
) -> dict:
    utc_hour, utc_minute = ist_to_utc(run_hour, run_minute)
    await repo.upsert_scheduler_settings(db, utc_hour, utc_minute, is_enabled)
    return {
        "status": "Scheduler updated",
        "run_hour": run_hour,
        "run_minute": run_minute,
        "is_enabled": is_enabled,
        "utc_hour": utc_hour,
        "utc_minute": utc_minute,
    }


async def list_reminders(db: AsyncSession) -> list[ReminderLogResponse]:
    rows = await repo.get_all_reminders(db)
    return [
        ReminderLogResponse(
            **row.ReminderLog.__dict__,
            customer_name=row.customer_name,
            customer_email=row.customer_email,
            invoice_number=row.invoice_number,
        )
        for row in rows
    ]
