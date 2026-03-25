from datetime import date
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.aging_config import AgingConfig
from src.data.repositories.aging_repository import get_active_aging_configs, get_overdue_invoices


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
    invoices = await get_overdue_invoices(db)
    configs = await get_active_aging_configs(db)

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
