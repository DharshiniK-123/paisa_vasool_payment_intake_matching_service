
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from src.data.models.postgres.scheduler_settings import SchedulerSettings
from src.data.clients.postgres_client import AsyncSessionLocal
from src.core.services.aging_service import get_overdue_invoices_with_bucket
from src.core.services.reminder_service import process_reminder

scheduler = AsyncIOScheduler()
JOB_ID    = "aging_reminder_job"


async def run_aging_and_reminders():
    try:
        async with AsyncSessionLocal() as db:
            overdue_items = await get_overdue_invoices_with_bucket(db)

            if not overdue_items:
                return

            generated = skipped = failed = 0

            for item in overdue_items:
                try:
                    reminder = await process_reminder(
                        item["invoice"],
                        item["days_overdue"],
                        item["config"],
                        db,
                    )
                    if reminder is None:
                        skipped += 1
                    else:
                        generated += 1
                except Exception as e:
                    failed += 1
                    print(f"[AGING] ERROR processing reminder for invoice {item['invoice'].invoice_number}: {e}")
            await db.commit()


    except Exception as e:
        raise


async def reschedule_aging_job(hour: int, minute: int):
    trigger = CronTrigger(hour=hour, minute=minute)
    if scheduler.get_job(JOB_ID):
        scheduler.reschedule_job(job_id=JOB_ID, trigger=trigger)
    else:
        scheduler.add_job(
            run_aging_and_reminders,
            trigger=trigger,
            id=JOB_ID,
            replace_existing=True,
            misfire_grace_time=3600,
        )


async def start_scheduler_from_db():
    hour, minute = 9, 0

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(SchedulerSettings).where(SchedulerSettings.id == 1)
        )
        settings = result.scalar_one_or_none()

        if settings is None:
            settings = SchedulerSettings(id=1, run_hour=9, run_minute=0, is_enabled=True)
            db.add(settings)
            await db.commit()
        elif settings.is_enabled:
            hour   = settings.run_hour
            minute = settings.run_minute

    await reschedule_aging_job(hour, minute)

    if not scheduler.running:
        scheduler.start()


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()