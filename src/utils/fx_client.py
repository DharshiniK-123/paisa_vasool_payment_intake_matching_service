import asyncio
import logging
from datetime import date
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.exchange_rate import ExchangeRate
from src.config.settings import settings

logger = logging.getLogger(__name__)

FRANKFURTER_BASE = settings.FRANKFURTER_BASE
_HTTP_TIMEOUT = settings.HTTP_TIMEOUT
MAX_RETRIES = settings.MAX_RETRIES


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
                break
        except httpx.TimeoutException as exc:
            last_exc = exc
            logger.error(
                "frankfurter_timeout",
                extra={"attempt": attempt, "from": from_cur, "to": to_cur, "date": str(rate_date)},
            )
            if attempt < MAX_RETRIES:
                await asyncio.sleep(2**attempt)
            else:
                raise RuntimeError(
                    f"Frankfurter request timed out after {MAX_RETRIES} retries "
                    f"for {from_cur}→{to_cur} on {rate_date}. "
                    "The FX service may be slow or unreachable from this environment."
                ) from exc

        except httpx.NetworkError as exc:
            last_exc = exc
            logger.error(
                "frankfurter_network_error",
                extra={"attempt": attempt, "error": str(exc)},
            )
            if attempt < MAX_RETRIES:
                await asyncio.sleep(2**attempt)
            else:
                raise RuntimeError(
                    f"Network error reaching Frankfurter for {from_cur}→{to_cur} on {rate_date}. "
                    "Check outbound internet access from the worker/container. "
                    f"Detail: {exc}"
                ) from exc

        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            logger.error(
                "frankfurter_http_error",
                extra={"status": status, "from": from_cur, "to": to_cur},
            )
            if status == 429:
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(2**attempt)
                    continue
                raise RuntimeError(
                    f"Frankfurter rate limit exceeded for {from_cur}→{to_cur}. "
                    "Too many requests from this environment. Consider a paid FX provider."
                ) from exc
            elif status == 404:
                raise RuntimeError(
                    f"No exchange rate found for {from_cur}→{to_cur} on {rate_date}. "
                    "Frankfurter may not support this currency pair or date."
                ) from exc
            elif status >= 500:
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(2**attempt)
                    continue
                raise RuntimeError(
                    f"Frankfurter server error ({status}) for {from_cur}→{to_cur}. "
                    "The FX service is currently unavailable."
                ) from exc
            else:
                raise RuntimeError(
                    f"Unexpected HTTP {status} from Frankfurter for {from_cur}→{to_cur}."
                ) from exc

        except Exception as exc:
            raise RuntimeError(
                f"Unexpected error fetching FX rate for {from_cur}→{to_cur} on {rate_date}: {exc}"
            ) from exc

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