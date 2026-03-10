from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from src.data.models.postgres.scheduler_settings import SchedulerSettings
from src.data.clients.postgres_client import AsyncSessionLocal
from src.core.services.aging_service import get_overdue_invoices_with_bucket
from src.core.services.reminder_service import process_reminder

scheduler = AsyncIOScheduler()
JOB_ID = "aging_reminder_job"


async def run_aging_and_reminders():
    try:
        async with AsyncSessionLocal() as db:
            overdue_items = await get_overdue_invoices_with_bucket(db)
            if not overdue_items:
                print("[SCHEDULER] Aging job: no overdue invoices found.")
                return
            generated = skipped = failed = 0
            for item in overdue_items:
                try:
                    reminder = await process_reminder(
                        item["invoice"], item["days_overdue"], item["config"], db
                    )
                    if reminder is None:
                        skipped += 1
                    elif reminder.status == "SENT":
                        generated += 1
                    else:
                        failed += 1
                except Exception as e:
                    print(f"[SCHEDULER] process_reminder failed for invoice {item['invoice'].id}: {e}")
                    failed += 1
            print(f"[SCHEDULER] Aging job done — sent: {generated}, skipped: {skipped}, failed: {failed}")
    except Exception as e:
        print(f"[SCHEDULER] Aging job failed: {e}")
        raise


async def reschedule_aging_job(hour: int, minute: int):
    trigger = CronTrigger(hour=hour, minute=minute)
    if scheduler.get_job(JOB_ID):
        scheduler.reschedule_job(job_id=JOB_ID, trigger=trigger)
        print(f"[SCHEDULER] Aging job rescheduled to {hour:02d}:{minute:02d} UTC")
    else:
        scheduler.add_job(
            run_aging_and_reminders,
            trigger=trigger,
            id=JOB_ID,
            replace_existing=True,
            misfire_grace_time=3600,
        )
        print(f"[SCHEDULER] Aging job added at {hour:02d}:{minute:02d} UTC")


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
            print("[SCHEDULER] No settings in DB — seeded defaults (09:00 UTC)")
        elif settings.is_enabled:
            hour   = settings.run_hour
            minute = settings.run_minute
            print(f"[SCHEDULER] Loaded time {hour:02d}:{minute:02d} UTC from DB")
        else:
            print("[SCHEDULER] is_enabled=False in DB, defaulting to 09:00 UTC")

    await reschedule_aging_job(hour, minute)
    if not scheduler.running:
        scheduler.start()
        print("[SCHEDULER] APScheduler started.")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        print("[SCHEDULER] APScheduler stopped.")
