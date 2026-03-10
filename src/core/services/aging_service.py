from datetime import date
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from src.data.models.postgres.invoice_data import InvoiceData
from src.data.models.postgres.aging_config import AgingConfig


async def get_aging_configs(db: AsyncSession) -> list[AgingConfig]:
    result = await db.execute(
        select(AgingConfig)
        .where(AgingConfig.is_active == True)
        .where(AgingConfig.severity != "SCHEDULER")
        .order_by(AgingConfig.due_days_from)
    )
    return result.scalars().all()


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


async def get_overdue_invoices(db: AsyncSession) -> list[InvoiceData]:
    today = date.today()
    result = await db.execute(
        select(InvoiceData).where(
            and_(
                InvoiceData.payment_status.in_(["UNPAID", "PARTIALLY_PAID"]),
                InvoiceData.due_date < today,
            )
        )
    )
    return result.scalars().all()


async def get_overdue_invoices_with_bucket(db: AsyncSession) -> list[dict]:
    invoices = await get_overdue_invoices(db)
    configs  = await get_aging_configs(db)

    print(f"[AGING] Scan: {len(invoices)} overdue invoices, {len(configs)} active configs")

    if not configs:
        print("[AGING] No active configs — go to Settings and enable your aging rules")
        return []

    result = []
    for invoice in invoices:
        days_overdue = calculate_days_overdue(invoice.due_date)
        config       = assign_aging_bucket(days_overdue, configs)
        if config is None:
            print(f"[AGING] Invoice {invoice.invoice_number} ({days_overdue} days overdue) — no matching bucket, skipping")
            continue
        print(f"[AGING] Invoice {invoice.invoice_number} ({days_overdue} days overdue) → bucket {config.severity}")
        result.append({
            "invoice":      invoice,
            "days_overdue": days_overdue,
            "config":       config,
        })
    return result
