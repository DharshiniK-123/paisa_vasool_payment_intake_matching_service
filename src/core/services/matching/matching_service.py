import logging
from datetime import date
from decimal import Decimal
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import delete as sa_delete
from src.utils.normalize import _normalize
from src.config.matching_config import MATCHING_CONFIG
from src.core.enums import MatchStatus
from src.data.models.postgres.invoice_data import InvoiceData
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
    save_suggested_match,
    save_successful_match,
    update_invoice_status,
)
from .pipeline import DEEP_MATCH_PIPELINE, run_scoring_pipeline
from .resolver import build_status_sentence, resolve_match
from src.data.repositories import matching_repository as repo



logger = logging.getLogger(__name__)

ZERO = Decimal("0.00")

CONCLUSIVE_STATUSES = (
    MatchStatus.FULL,
    MatchStatus.PARTIAL,
    MatchStatus.OVERPAYMENT,
    MatchStatus.MANUALLY_MATCHED,
)


def _validate_payment(payment) -> str | None:
    """
    Returns an error reason string if the payment is invalid, else None.

    NOTE: Missing invoice_no is NO LONGER a hard failure here.
    Payments without an invoice number fall through to deep match.
    Only a zero/negative amount is a hard stop.
    """
    pay_amount = Decimal(str(payment.payment_amount))

    if pay_amount <= ZERO:
        return (
            f"Payment amount is {payment.currency} {pay_amount:,.2f}, which is not a valid "
            "amount. Payments must be greater than zero. This record requires manual review."
        )

    return None


async def _process_invoice(
    payment,
    invoice,
    invoice_nos:         list[str],
    remaining_pay:       Decimal,
    db:                  AsyncSession,
    converted:           bool           = False,
    fx_rate:             Decimal | None = None,
    original_pay_amount: Decimal | None = None,
) -> tuple[MatchingPaymentInvoice | None, Decimal]:
    """
    Attempt to match a single invoice against the remaining payment.
    Used for both normal and FX-converted matches.
    """
    if await is_duplicate(payment.id, invoice.id, db):
        rec = await save_duplicate_match(payment.id, invoice, db)
        return rec, remaining_pay

    already_matched = await get_already_matched_amount(invoice.id, db)
    inv_remaining   = Decimal(str(invoice.total_amount)) - already_matched
    if inv_remaining <= ZERO:
        return None, remaining_pay

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

    if converted and fx_rate:
        consumed = (matched_amount / fx_rate).quantize(Decimal("0.01"))
    else:
        consumed = matched_amount

    return rec, remaining_pay - consumed


async def _run_deep_match(
    payment,
    candidates_deep: list[InvoiceData],
    remaining_pay:   Decimal,
    db:              AsyncSession,
) -> list[MatchingPaymentInvoice]:
    """
    Deep match: no invoice number provided.
    Score all open customer invoices using DEEP_MATCH_PIPELINE
    (skips InvoiceNumberStrategy which would hard-disqualify everything).
    """
    scored: list[tuple[int, InvoiceData]] = []

    for invoice in candidates_deep:
        already_matched = await get_already_matched_amount(invoice.id, db)
        inv_remaining   = Decimal(str(invoice.total_amount)) - already_matched
        if inv_remaining <= ZERO:
            continue

        score, _ = run_scoring_pipeline(
            payment=payment,
            invoice=invoice,
            invoice_nos=[],
            remaining_pay=remaining_pay,
            inv_remaining=inv_remaining,
            pipeline=DEEP_MATCH_PIPELINE,
        )

        if score >= MATCHING_CONFIG.deep_match_threshold:
            scored.append((score, invoice))

    if not scored:
        return []

    # Sort highest score first
    scored.sort(key=lambda x: x[0], reverse=True)

    records: list[MatchingPaymentInvoice] = []

    if len(scored) == 1 or (scored[0][0] - scored[1][0] >= 10):
        best_score, best_invoice = scored[0]
        already_matched = await get_already_matched_amount(best_invoice.id, db)
        inv_remaining   = Decimal(str(best_invoice.total_amount)) - already_matched
        _, matched_amount, amount_pending = resolve_match(remaining_pay, inv_remaining)

        rec = await save_suggested_match(
            payment_id=payment.id,
            invoice_id=int(best_invoice.id),
            matched_amount=matched_amount,
            amount_pending=amount_pending,
            score=best_score,
            match_reason=(
                f"Deep match: no invoice number provided. "
                f"Best candidate: invoice '{best_invoice.invoice_number}' "
                f"matched by amount ({payment.currency} {remaining_pay:,.2f}) "
                f"and customer. Score: {best_score}/60. "
                "Please review and approve or reject this match."
            ),
            db=db,
        )
        records.append(rec)

    else:
        logger.info(
            "deep_match_multiple_candidates",
            extra={
                "payment_id": payment.id,
                "candidates": [(s, inv.invoice_number) for s, inv in scored],
            },
        )
        for rank, (score, invoice) in enumerate(scored, start=1):
            already_matched = await get_already_matched_amount(invoice.id, db)
            inv_remaining   = Decimal(str(invoice.total_amount)) - already_matched
            _, matched_amount, amount_pending = resolve_match(remaining_pay, inv_remaining)

            rec = await save_suggested_match(
                payment_id=payment.id,
                invoice_id=int(invoice.id),
                matched_amount=matched_amount,
                amount_pending=amount_pending,
                score=score,
                match_reason=(
                    f"Deep match: no invoice number provided. "
                    f"Multiple invoices match with similar confidence "
                    f"(candidate {rank} of {len(scored)}): "
                    f"invoice '{invoice.invoice_number}', score {score}/60. "
                    "Manual selection required — please approve one and reject the others."
                ),
                db=db,
            )
            records.append(rec)

    return records


async def _rematch_payments_for_invoice(
    invoice_number: str,
    customer_id: int,
    db: AsyncSession,
) -> None:
    """
    Called after a new invoice is saved.
    Finds every payment for the same customer whose invoice_no
    matches this invoice number and that has NO successful match record yet,
    then re-runs the matching pipeline for each such payment.

    This handles the case: payment uploaded first → invoice uploaded later.
    """
    from src.utils.extract_multiple_invoice_nos import _extract_multiple_invoice_nos

    inv_norm = _normalize(invoice_number)

    result = await db.execute(
        select(PaymentDetail).where(
            PaymentDetail.customer_id == customer_id,
            PaymentDetail.is_deleted.is_(False),
        )
    )
    payments = result.scalars().all()

    for payment in payments:
        payment_invoice_nos = _extract_multiple_invoice_nos((payment.invoice_no or "").strip())
        number_hit = any(
            n == inv_norm or inv_norm in n or n in inv_norm for n in payment_invoice_nos
        )
        if not number_hit:
            continue

        existing = await db.execute(
            select(MatchingPaymentInvoice).where(
                MatchingPaymentInvoice.payment_detail_id == payment.id,
                MatchingPaymentInvoice.match_status.in_([
                    MatchStatus.FULL,
                    MatchStatus.PARTIAL,
                    MatchStatus.OVERPAYMENT,
                ]),
            )
        )
        if existing.scalars().first() is not None:
            continue
        await db.execute(
            sa_delete(MatchingPaymentInvoice).where(
                MatchingPaymentInvoice.payment_detail_id == payment.id,
                MatchingPaymentInvoice.match_status == MatchStatus.FAILED,
            )
        )
        await db.flush()

        logger.info(
            "rematch_payment",
            extra={"payment_id": payment.id, "invoice_number": invoice_number},
        )
        await run_matching_for_payment(int(payment.id), db)



async def run_matching_for_payment(
    payment_id: int,
    db:         AsyncSession,
    hint_invoice_id: int | None = None,
) -> list:
    """
    Match a payment against open invoices.

    Steps:
      1. Idempotency — return existing records if already processed or pending review
      2. Validate payment (amount > 0)
      3. Fetch + categorize invoice candidates
      4. If invoice_no present: same-currency matches
      5. If invoice_no present: FX-converted matches
      6. If invoice_no absent:  deep match (amount + customer scoring)
      7. Save unmatched remainder if any
      8. Update invoice payment statuses
      9. Commit
    """

    # 1. Idempotency (now also blocks re-run for SUGGESTED)
    if await payment_already_processed(payment_id, db):
        logger.info("payment_already_processed", extra={"payment_id": payment_id})
        return await fetch_existing_records(payment_id, db)

    # 2. Fetch payment
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

    validation_error = _validate_payment(payment)
    if validation_error:
        rec: MatchingPaymentInvoice | None = await save_failed_match(
            payment_id, validation_error, db
        )
        await db.commit()
        return [rec] if rec else []

    pay_amount    = Decimal(str(payment.payment_amount))
    remaining_pay = pay_amount
    records:      list[MatchingPaymentInvoice] = []

    invoice_nos = _extract_multiple_invoice_nos((payment.invoice_no or "").strip())

    # 3. Fetch candidates
    candidates = await CandidateFetcher(db).fetch(payment, invoice_nos)

    if not candidates.has_open():
        reason = candidates.best_failure_reason(payment, invoice_nos)
        rec = await save_failed_match(payment_id, reason, db)
        await db.commit()
        return [rec] if rec else []

    # 4. Same-currency matches (invoice_no path)
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

    # 5. FX-converted matches (invoice_no path)
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

    # 6. Deep match (no invoice_no path)
    if not records and candidates.deep_candidates:
        logger.info(
            "deep_match_attempt",
            extra={
                "payment_id": payment_id,
                "candidates": len(candidates.deep_candidates),
            },
        )
        deep_records = await _run_deep_match(
            payment=payment,
            candidates_deep=candidates.deep_candidates,
            remaining_pay=remaining_pay,
            db=db,
        )
        if deep_records:
            records.extend(deep_records)
            await db.commit()
            return records
        else:
            rec = await save_failed_match(
                payment_id,
                (
                    "No invoice number was provided and no open invoices could be matched "
                    f"by amount ({payment.currency} {pay_amount:,.2f}) with sufficient "
                    "confidence. Manual assignment is required."
                ),
                db,
            )
            records.append(rec)
            await db.commit()
            return records

    # 6b. Deep match — FX-only path (no invoice_no, no same-currency invoices, FX exist)
    if not records and not candidates.deep_candidates and candidates.fx_mismatch:
        fx_currencies = sorted({str(inv.currency) for inv in candidates.fx_mismatch})
        logger.info(
            "deep_match_fx_only",
            extra={
                "payment_id": payment_id,
                "fx_currencies": fx_currencies,
                "payment_currency": str(payment.currency),
            },
        )
        rec = await save_failed_match(
            payment_id,
            (
                f"No invoice number was provided and all open invoices for this customer "
                f"are in a different currency ({', '.join(fx_currencies)}) from the payment "
                f"({payment.currency}). Automatic FX deep-matching is not supported without "
                "an invoice number. Please assign this payment manually with the correct "
                "invoice and verify the exchange rate."
            ),
            db,
        )
        records.append(rec)
        await db.commit()
        return records

    # 7. Unmatched remainder (normal path)
    last_status = next(
        (r.match_status for r in reversed(records)
         if r.match_status in CONCLUSIVE_STATUSES),
        None,
    )
    overpayment_absorbed = (last_status == MatchStatus.OVERPAYMENT and remaining_pay > ZERO)

    if remaining_pay > ZERO and not overpayment_absorbed:
        successful = [r for r in records if r.match_status in CONCLUSIVE_STATUSES]
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

    # 8. Update invoice statuses + commit
    matched_invoice_ids = {
        r.invoice_id for r in records
        if r.invoice_id and r.match_status in CONCLUSIVE_STATUSES
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



async def get_matches_by_payment(payment_id: int, db: AsyncSession) -> list[MatchingPaymentInvoice]:
    return await repo.get_matches_by_payment_id(payment_id, db)


async def get_matches_by_invoice(invoice_id: int, db: AsyncSession) -> list[MatchingPaymentInvoice]:
    return await repo.get_matches_by_invoice_id(invoice_id, db)


async def get_unmatched_payments(db: AsyncSession) -> list[dict]:
    rows = await repo.get_unmatched_payments(db)
    return [dict(row) for row in rows]


async def get_unmatched_invoices(db: AsyncSession) -> list[dict]:
    rows = await repo.get_unmatched_invoices(db)
    return [
        {
            **{k: v for k, v in row.InvoiceData.__dict__.items() if not k.startswith("_")},
            "customer_name": row.customer_name,
            "customer_email": row.customer_email,
        }
        for row in rows
    ]


async def get_invoice_detail(invoice_id: int, db: AsyncSession) -> dict | None:
    row = await repo.get_invoice_detail(invoice_id, db)
    if not row:
        return None
    data = {k: v for k, v in row.InvoiceData.__dict__.items() if not k.startswith("_")}
    data["customer_name"] = row.customer_name
    data["customer_email"] = row.customer_email
    return data


async def get_payment_detail(payment_id: int, db: AsyncSession) -> dict | None:
    row = await repo.get_payment_detail(payment_id, db)
    if not row:
        return None
    data = {k: v for k, v in row.PaymentDetail.__dict__.items() if not k.startswith("_")}
    data["payer_name"] = row.payer_name
    data["payer_email"] = row.payer_email
    data["amount"] = data.pop("payment_amount", None)
    data["payment_date"] = data.pop("paid_date", None)
    data["reference_number"] = data.pop("payment_reference", None)
    return data


async def get_recent_matches(limit: int, db: AsyncSession) -> list[MatchingPaymentInvoice]:
    return await repo.get_recent_matches(limit, db)


async def get_discrepancies(db: AsyncSession) -> list[dict]:
    rows = await repo.get_discrepancies(db)

    invoice_ids_with_overpayment = {
        row["invoice_id"]
        for row in rows
        if row["match_status"] == "OVERPAYMENT" and row["invoice_id"] is not None
    }
    return [
        row
        for row in rows
        if not (
            row["match_status"] == "PARTIAL" and row["invoice_id"] in invoice_ids_with_overpayment
        )
    ]


async def get_dashboard_summary(db: AsyncSession) -> dict:
    all_matches = await repo.get_all_matches(db)
    if not all_matches:
        return {
            "FULL": [], "PARTIAL": [], "OVERPAYMENT": [],
            "DUPLICATE": [], "FAILED": [],
            "SUGGESTED": [],        
            "MANUALLY_MATCHED": [], 
        }
    return {
        status: [m for m in all_matches if m.match_status == status]
        for status in [
            "FULL", "PARTIAL", "OVERPAYMENT",
            "DUPLICATE", "FAILED",
            "SUGGESTED",
            "MANUALLY_MATCHED",
        ]
    }


async def get_pending_review(db: AsyncSession) -> list[dict]:
    """
    Returns all SUGGESTED match records enriched with invoice and payment context
    so the frontend can render the review UI without extra calls.
    """
    result = await db.execute(
        select(
            MatchingPaymentInvoice,
            InvoiceData.invoice_number,
            InvoiceData.total_amount.label("invoice_amount"),
            PaymentDetail.payment_amount,
            PaymentDetail.currency,
            PaymentDetail.paid_date,
        )
        .join(InvoiceData,  InvoiceData.id  == MatchingPaymentInvoice.invoice_id)
        .join(PaymentDetail, PaymentDetail.id == MatchingPaymentInvoice.payment_detail_id)
        .where(MatchingPaymentInvoice.match_status == "SUGGESTED")
        .order_by(MatchingPaymentInvoice.created_at.desc())
    )

    rows = result.all()
    return [
        {
            "match_id":       row.MatchingPaymentInvoice.id,
            "payment_id":     row.MatchingPaymentInvoice.payment_detail_id,
            "invoice_id":     row.MatchingPaymentInvoice.invoice_id,
            "invoice_number": row.invoice_number,
            "invoice_amount": row.invoice_amount,
            "payment_amount": row.payment_amount,
            "currency":       row.currency,
            "paid_date":      row.paid_date,
            "matched_amount": row.MatchingPaymentInvoice.matched_amount,
            "amount_pending": row.MatchingPaymentInvoice.amount_pending,
            "match_score":    row.MatchingPaymentInvoice.match_score,
            "match_reason":   row.MatchingPaymentInvoice.match_reason,
            "created_at":     row.MatchingPaymentInvoice.created_at,
        }
        for row in rows
    ]