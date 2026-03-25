"""
matching_service.py
───────────────────
Orchestrates payment-to-invoice matching.

This file contains ONLY coordination logic — no scoring weights,
no DB query construction, no message strings.
Each concern lives in its own module:

  config/matching_config.py          → weights + thresholds
  matching/candidate_fetcher.py      → DB queries + invoice categorization
  matching/pipeline.py               → scoring pipeline (strategy pattern)
  matching/resolver.py               → FULL / PARTIAL / OVERPAYMENT resolution
  matching/db_writer.py              → all DB writes + invoice status updates
  matching/strategies/               → one file per scoring signal
"""

import logging
from datetime import date
from decimal import Decimal

from typing import cast
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.matching_config import MATCHING_CONFIG
from src.data.models.postgres.matching_payment_invoice import MatchingPaymentInvoice
from src.data.models.postgres.payment_detail import PaymentDetail
from src.utils.extract_multiple_invoice_nos import _extract_multiple_invoice_nos
from src.utils.fx_client import get_exchange_rate

from .candidate_fetcher import CandidateFetcher
from .db_writer import (
    fetch_existing_records,
    get_already_matched_amount,
    is_duplicate,
    payment_already_processed,
    save_duplicate_match,
    save_failed_match,
    save_successful_match,
    update_invoice_status,
)
from .pipeline import run_scoring_pipeline
from .resolver import build_status_sentence, resolve_match

logger = logging.getLogger(__name__)

ZERO = Decimal("0.00")


# ─────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────

def _validate_payment(payment) -> str | None:
    """Returns an error reason string if the payment is invalid, else None."""
    pay_amount = Decimal(str(payment.payment_amount))

    if pay_amount <= ZERO:
        return (
            f"Payment amount is {payment.currency} {pay_amount:,.2f}, which is not a valid "
            "amount. Payments must be greater than zero. This record requires manual review."
        )

    if not (payment.invoice_no or "").strip():
        return (
            "No invoice number was provided with this payment. "
            "The payment cannot be automatically matched and requires manual review."
        )

    return None


async def _process_invoice(
    payment,
    invoice,
    invoice_nos:   list[str],
    remaining_pay: Decimal,
    db:            AsyncSession,
    converted:           bool           = False,
    fx_rate:             Decimal | None = None,
    original_pay_amount: Decimal | None = None,
) -> tuple[MatchingPaymentInvoice | None, Decimal]:
    """
    Attempt to match a single invoice against the remaining payment.

    Returns:
        (record, updated_remaining_pay)
        record is None if the invoice was skipped (zero balance).
    """
    # Duplicate guard
    if await is_duplicate(payment.id, invoice.id, db):
        rec = await save_duplicate_match(payment.id, invoice, db)
        return rec, remaining_pay

    # Invoice may already be fully covered by other payments
    already_matched = await get_already_matched_amount(invoice.id, db)
    inv_remaining   = Decimal(str(invoice.total_amount)) - already_matched
    if inv_remaining <= ZERO:
        return None, remaining_pay

    # Choose what amount to score against (converted or raw)
    pay_to_score = (
        (remaining_pay * fx_rate).quantize(Decimal("0.01"))
        if converted and fx_rate
        else remaining_pay
    )

    score, reasons = run_scoring_pipeline(
        payment=payment,
        invoice=invoice,
        invoice_nos=invoice_nos,
        remaining_pay=pay_to_score,
        inv_remaining=inv_remaining,
        converted=converted,
        fx_rate=fx_rate,
        original_pay_amount=original_pay_amount,
    )

    if score < MATCHING_CONFIG.min_match_score:
        rec = await save_failed_match(
            payment.id,
            (
                f"Low confidence match for invoice '{invoice.invoice_number}' "
                f"(score: {score}/100). "
                + " ".join(reasons)
                + " Manual review is recommended."
            ),
            db,
            invoice_id=invoice.id,
            score=score,
        )
        return rec, remaining_pay

    match_status, matched_amount, amount_pending = resolve_match(pay_to_score, inv_remaining)

    status_sentence = build_status_sentence(
        match_status=match_status,
        invoice=invoice,
        payment=payment,
        matched_amount=matched_amount,
        amount_pending=amount_pending,
        remaining_pay=pay_to_score,
        inv_remaining=inv_remaining,
        converted=converted,
        fx_rate=fx_rate,
    )

    rec = await save_successful_match(
        payment_id=payment.id,
        invoice_id=invoice.id,
        matched_amount=matched_amount,
        amount_pending=amount_pending,
        score=score,
        match_status=match_status,
        match_reason=" ".join(reasons) + " " + status_sentence,
        db=db,
    )

    # Deduct from remaining in original payment currency
    if converted and fx_rate:
        consumed = (matched_amount / fx_rate).quantize(Decimal("0.01"))
    else:
        consumed = matched_amount

    return rec, remaining_pay - consumed


# ─────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────

async def run_matching_for_payment(payment_id: int, db: AsyncSession) -> list:
    """
    Match a payment against open invoices.

    Steps:
      1. Idempotency — return existing records if already processed
      2. Validate payment (amount > 0, invoice_no present)
      3. Fetch + categorize invoice candidates
      4. Process same-currency matches first
      5. Process FX-converted matches second
      6. Save unmatched remainder if any
      7. Update invoice payment statuses
      8. Commit
    """

    # ── 1. Idempotency ───────────────────────────────────────────────────────
    if await payment_already_processed(payment_id, db):
        logger.info("payment_already_processed", extra={"payment_id": payment_id})
        return await fetch_existing_records(payment_id, db)

    # ── 2. Fetch payment ─────────────────────────────────────────────────────
    result = await db.execute(
        select(PaymentDetail).where(
            PaymentDetail.id == payment_id,
            PaymentDetail.is_deleted.is_(False),
        )
    )
    payment = result.scalar_one_or_none()
    if not payment:
        logger.warning("payment_not_found", extra={"payment_id": payment_id})
        return []

    logger.info(
        "matching_start",
        extra={
            "payment_id": payment_id,
            "amount":     str(payment.payment_amount),
            "currency":   payment.currency,
            "invoice_no": payment.invoice_no,
        },
    )

    # ── 3. Validate ──────────────────────────────────────────────────────────
    validation_error = _validate_payment(payment)
    if validation_error:
        rec: MatchingPaymentInvoice | None = await save_failed_match(payment_id, validation_error, db)
        await db.commit()
        return [rec] if rec else []

    pay_amount    = Decimal(str(payment.payment_amount))
    remaining_pay = pay_amount
    records:      list[MatchingPaymentInvoice] = []

    invoice_nos = _extract_multiple_invoice_nos((payment.invoice_no or "").strip())

    # ── 4. Fetch candidates ──────────────────────────────────────────────────
    candidates = await CandidateFetcher(db).fetch(payment, invoice_nos)

    if not candidates.has_open():
        reason = candidates.best_failure_reason(payment, invoice_nos)
        rec = await save_failed_match(payment_id, reason, db)
        await db.commit()
        return [rec] if rec else []

    # ── 5. Same-currency matches ─────────────────────────────────────────────
    for invoice in candidates.same_currency:
        if remaining_pay <= ZERO:
            break

        rec, remaining_pay = await _process_invoice(
            payment=payment,
            invoice=invoice,
            invoice_nos=invoice_nos,
            remaining_pay=remaining_pay,
            db=db,
        )
        if rec is not None:
            records.append(rec)

    # ── 6. FX-converted matches ──────────────────────────────────────────────
    for invoice in candidates.fx_mismatch:
        if remaining_pay <= ZERO:
            break

        try:
            fx_rate = await get_exchange_rate(
                cast(date, payment.paid_date),
                str(payment.currency),
                str(invoice.currency),
                db,
            )
        except RuntimeError as exc:
            rec = await save_failed_match(
                payment_id,
                f"Currency mismatch: payment is in {payment.currency} but invoice "
                f"'{invoice.invoice_number}' is in {invoice.currency}. "
                f"Automatic FX conversion failed: {exc}. Manual review required.",
                db,
                invoice_id=int(invoice.id),
            )
            records.append(rec)
            continue

        rec, remaining_pay = await _process_invoice(
            payment=payment,
            invoice=invoice,
            invoice_nos=invoice_nos,
            remaining_pay=remaining_pay,
            db=db,
            converted=True,
            fx_rate=fx_rate,
            original_pay_amount=remaining_pay,
        )
        if rec is not None:
            records.append(rec)

    # ── 7. Unmatched remainder ───────────────────────────────────────────────
    last_status = next(
        (r.match_status for r in reversed(records)
         if r.match_status in ("FULL", "PARTIAL", "OVERPAYMENT")),
        None,
    )
    overpayment_absorbed = (
        last_status == "OVERPAYMENT" and remaining_pay > ZERO
    )

    if remaining_pay > ZERO and not overpayment_absorbed:
        successful = [
            r for r in records
            if r.match_status in ("FULL", "PARTIAL", "OVERPAYMENT")
        ]
        if successful:
            applied = ", ".join(f"'{r.invoice_id}'" for r in successful)
            reason  = (
                f"{payment.currency} {remaining_pay:,.2f} of the payment could not be "
                f"matched to any invoice after applying amounts to invoice(s) {applied}. "
                "The remaining amount requires manual review."
            )
        else:
            reason = (
                f"The full payment amount of {payment.currency} {pay_amount:,.2f} "
                "could not be matched to any open invoice. "
                "Please verify the invoice number and customer details."
            )
        rec = await save_failed_match(payment_id, reason, db)
        records.append(rec)

    # ── 8. Update invoice statuses + commit ──────────────────────────────────
    matched_invoice_ids = {
        r.invoice_id for r in records
        if r.invoice_id and r.match_status in ("FULL", "PARTIAL", "OVERPAYMENT")
    }
    for invoice_id in matched_invoice_ids:
        await update_invoice_status(int(invoice_id), db)

    await db.commit()

    logger.info(
        "matching_complete",
        extra={
            "payment_id":    payment_id,
            "records":       len(records),
            "remaining_pay": str(remaining_pay),
        },
    )

    return records
