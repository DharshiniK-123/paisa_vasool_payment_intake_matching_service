from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from src.data.models.postgres.aging_config import AgingConfig
from src.data.clients.postgres_client import AsyncSessionLocal
from src.core.services.aging_service import get_overdue_invoices_with_bucket
from src.core.services.reminder_service import process_reminder


scheduler = AsyncIOScheduler()


async def run_aging_and_reminders():
    async with AsyncSessionLocal() as db:
        try:
            overdue_items = await get_overdue_invoices_with_bucket(db)
            if not overdue_items:
                return
            generated = skipped = failed = 0
            for item in overdue_items:
                invoice      = item["invoice"]
                days_overdue = item["days_overdue"]
                config       = item["config"]
                try:
                    reminder = await process_reminder(invoice, days_overdue, config, db)
                    if reminder is None:
                        skipped += 1
                    elif reminder.status == "GENERATED":
                        generated += 1
                    else:
                        failed += 1
                except Exception as e:
                    failed += 1
        except Exception as e:
            raise


async def reschedule_aging_job(hour: int, minute: int):
    scheduler.reschedule_job(
        job_id="aging_reminder_job",
        trigger=CronTrigger(hour=hour, minute=minute),
    )


async def start_scheduler_from_db():
    hour, minute = 9, 0  
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AgingConfig).where(AgingConfig.severity == "SCHEDULER")
        )
        scheduler_config = result.scalar_one_or_none()
        if scheduler_config and scheduler_config.run_hour is not None:
            hour   = scheduler_config.run_hour
            minute = scheduler_config.run_minute or 0
    scheduler.add_job(
        run_aging_and_reminders,
        trigger=CronTrigger(hour=hour, minute=minute),
        id="aging_reminder_job",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    
def stop_scheduler():
    scheduler.shutdown()