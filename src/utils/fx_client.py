import asyncio
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
_HTTP_TIMEOUT = 10.0
MAX_RETRIES = 3


def _is_transient_http_error(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return False


async def get_exchange_rate(
    rate_date: date,
    from_currency: str,
    to_currency: str,
    db: AsyncSession,
) -> Decimal:
    from_cur = from_currency.upper().strip()
    to_cur = to_currency.upper().strip()

    if from_cur == to_cur:
        return Decimal("1.00000000")

    cached = await db.execute(
        select(ExchangeRate).where(
            ExchangeRate.rate_date == rate_date,
            ExchangeRate.from_currency == from_cur,
            ExchangeRate.to_currency == to_cur,
        )
    )
    row = cached.scalar_one_or_none()
    if row:
        return Decimal(str(row.rate))

    url = f"{FRANKFURTER_BASE}/{rate_date.isoformat()}"
    params = {"from": from_cur, "to": to_cur}

    last_exc: Exception = RuntimeError("unreachable")
    for attempt in range(MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
                break  # Success
        except Exception as exc:
            last_exc = exc
            if attempt < MAX_RETRIES and _is_transient_http_error(exc):
                wait = 2**attempt
                logger.warning(
                    "frankfurter_retry",
                    extra={
                        "attempt": attempt,
                        "wait_secs": wait,
                        "error": str(exc),
                    },
                )
                await asyncio.sleep(wait)
            else:
                raise RuntimeError(
                    f"Frankfurter request failed for {from_cur}→{to_cur} on {rate_date}: {exc}"
                ) from exc
    else:
        raise last_exc

    rates: dict = data.get("rates", {})
    if to_cur not in rates:
        raise RuntimeError(
            f"Frankfurter did not return a rate for {to_cur} "
            f"(from {from_cur} on {rate_date}). Response: {data}"
        )

    rate = Decimal(str(rates[to_cur]))

    stmt = (
        pg_insert(ExchangeRate)
        .values(
            rate_date=rate_date,
            from_currency=from_cur,
            to_currency=to_cur,
            rate=rate,
        )
        .on_conflict_do_nothing(constraint="uq_exchange_rate_date_pair")
    )
    await db.execute(stmt)
    await db.flush()

    return rate
