from datetime import date

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.enums import AgingSeverity, InvoicePaymentStatus
from src.data.models.postgres.aging_config import AgingConfig
from src.data.models.postgres.customer import Customer
from src.data.models.postgres.invoice_data import InvoiceData
from src.data.models.postgres.reminder_log import ReminderLog
from src.data.models.postgres.scheduler_settings import SchedulerSettings


async def get_all_aging_configs(db: AsyncSession) -> list[AgingConfig]:
    result = await db.execute(
        select(AgingConfig)
        .where(AgingConfig.severity != AgingSeverity.SCHEDULER)
        .order_by(AgingConfig.id.asc())
    )
    return list(result.scalars().all())


async def get_aging_config_by_id(config_id: int, db: AsyncSession) -> AgingConfig | None:
    result = await db.execute(select(AgingConfig).where(AgingConfig.id == config_id))
    return result.scalar_one_or_none()


async def get_aging_config_by_severity(severity: str, db: AsyncSession) -> AgingConfig | None:
    result = await db.execute(select(AgingConfig).where(AgingConfig.severity == severity))
    return result.scalar_one_or_none()


async def create_aging_config(db: AsyncSession, data: dict) -> AgingConfig:
    config = AgingConfig(**data)
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return config


async def update_aging_config(config: AgingConfig, updates: dict, db: AsyncSession) -> AgingConfig:
    for key, value in updates.items():
        setattr(config, key, value)
    await db.commit()
    await db.refresh(config)
    return config


async def delete_aging_config(config: AgingConfig, db: AsyncSession) -> None:
    await db.delete(config)
    await db.commit()


async def get_scheduler_settings(db: AsyncSession) -> SchedulerSettings | None:
    result = await db.execute(select(SchedulerSettings).where(SchedulerSettings.id == 1))
    return result.scalar_one_or_none()


async def upsert_scheduler_settings(
    db: AsyncSession, utc_hour: int, utc_minute: int, is_enabled: bool
) -> SchedulerSettings:
    row = await get_scheduler_settings(db)
    if row is None:
        row = SchedulerSettings(
            id=1,
            run_hour=utc_hour,
            run_minute=utc_minute,
            is_enabled=is_enabled)

        db.add(row)
    else:
        row.run_hour = utc_hour  # type: ignore[assignment]
        row.run_minute = utc_minute  # type: ignore[assignment]
        row.is_enabled = is_enabled  # type: ignore[assignment]
    await db.commit()
    return row

async def get_active_aging_configs(db: AsyncSession) -> list[AgingConfig]:
    result = await db.execute(
        select(AgingConfig)
        .where(AgingConfig.is_active)
        .where(AgingConfig.severity != AgingSeverity.SCHEDULER)
        .order_by(AgingConfig.due_days_from)
    )
    return list(result.scalars().all())


async def get_overdue_invoices(db: AsyncSession) -> list[InvoiceData]:
    today = date.today()
    result = await db.execute(
        select(InvoiceData).where(
            and_(
                InvoiceData.payment_status.in_([
                    InvoicePaymentStatus.UNPAID,
                    InvoicePaymentStatus.PARTIALLY_PAID,
                ]),
                InvoiceData.due_date < today,
            )
        )
    )
    return list(result.scalars().all())


async def get_all_reminders(db: AsyncSession) -> list:
    result = await db.execute(
        select(
            ReminderLog,
            Customer.name.label("customer_name"),
            Customer.email.label("customer_email"),
            InvoiceData.invoice_number.label("invoice_number"),
        )
        .join(Customer, ReminderLog.customer_id == Customer.id)
        .join(InvoiceData, ReminderLog.invoice_id == InvoiceData.id)
        .order_by(ReminderLog.sent_at.desc())
    )
    return list(result.all())
