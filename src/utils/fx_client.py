import logging
from datetime import date
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.exchange_rate import ExchangeRate

logger = logging.getLogger(__name__)

FRANKFURTER_BASE = "https://api.frankfurter.app"
_HTTP_TIMEOUT    = 10.0   # seconds


async def get_exchange_rate(rate_date: date,from_currency: str,to_currency: str,db: AsyncSession,
) -> Decimal:
    
    from_cur = from_currency.upper().strip()
    to_cur   = to_currency.upper().strip()

    if from_cur == to_cur:
        return Decimal("1.00000000")

    # ── 1. Cache look-up ──────────────────────────────────────────────────────
    cached = await db.execute(
        select(ExchangeRate).where(
            ExchangeRate.rate_date     == rate_date,
            ExchangeRate.from_currency == from_cur,
            ExchangeRate.to_currency   == to_cur,
        )
    )
    row = cached.scalar_one_or_none()
    if row:
        logger.debug(
            "FX cache hit: %s → %s on %s = %s",
            from_cur, to_cur, rate_date, row.rate,
        )
        return Decimal(str(row.rate))

    # ── 2. Fetch from Frankfurter ─────────────────────────────────────────────
    # Format: GET /{YYYY-MM-DD}?from=XXX&to=YYY
    url = f"{FRANKFURTER_BASE}/{rate_date.isoformat()}"
    params = {"from": from_cur, "to": to_cur}

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise RuntimeError(
            f"Frankfurter request failed for {from_cur}→{to_cur} on {rate_date}: {exc}"
        ) from exc

    rates: dict = data.get("rates", {})
    if to_cur not in rates:
        raise RuntimeError(
            f"Frankfurter did not return a rate for {to_cur} "
            f"(from {from_cur} on {rate_date}). Response: {data}"
        )

    rate = Decimal(str(rates[to_cur]))

    # ── 3. Persist (upsert — safe under concurrent access) ────────────────────
    stmt = (
        pg_insert(ExchangeRate)
        .values(
            rate_date     = rate_date,
            from_currency = from_cur,
            to_currency   = to_cur,
            rate          = rate,
        )
        .on_conflict_do_nothing(
            constraint="uq_exchange_rate_date_pair"
        )
    )
    await db.execute(stmt)
    await db.flush()

    logger.info(
        "FX rate stored: %s → %s on %s = %s",
        from_cur, to_cur, rate_date, rate,
    )
    return rate
