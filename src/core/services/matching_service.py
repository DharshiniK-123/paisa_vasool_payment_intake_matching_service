import re
from decimal import Decimal
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.utils.normalize import _normalize
from src.utils.extract_multiple_invoice_nos import _extract_multiple_invoice_nos
from src.data.models.postgres.invoice_data import InvoiceData
from src.data.models.postgres.payment_detail import PaymentDetail
from src.data.models.postgres.matching_payment_invoice import MatchingPaymentInvoice

ROUNDING_TOLERANCE = Decimal("1.00")

async def _get_already_matched_amount(invoice_id: int, db: AsyncSession) -> Decimal:
    result = await db.execute(
        select(func.coalesce(func.sum(MatchingPaymentInvoice.matched_amount), 0))
        .where(
            and_(
                MatchingPaymentInvoice.invoice_id == invoice_id,
                MatchingPaymentInvoice.match_status.in_(["FULL", "PARTIAL", "OVERPAYMENT"]),
            )
        )
    )
    return Decimal(str(result.scalar()))

async def _is_duplicate(payment_id: int, invoice_id: int, db: AsyncSession) -> bool:

    result = await db.execute(
        select(MatchingPaymentInvoice).where(
            and_(
                MatchingPaymentInvoice.payment_detail_id == payment_id,
                MatchingPaymentInvoice.invoice_id == invoice_id,
                MatchingPaymentInvoice.match_status.in_(["FULL", "PARTIAL"]),
            )
        )
    )

    rows = result.scalars().all()

    print("Duplicate check rows:")
    for row in rows:
        print(
            "id:", row.id,
            "payment_detail_id:", row.payment_detail_id,
            "invoice_id:", row.invoice_id,
            "status:", row.match_status,
            "matched_amount:", row.matched_amount
        )

    return len(rows) > 0


async def _update_invoice_status(invoice_id: int, db: AsyncSession) -> None:
    result = await db.execute(select(InvoiceData).where(InvoiceData.id == invoice_id))
    invoice = result.scalar_one_or_none()
    if not invoice:
        return

    total_matched = await _get_already_matched_amount(invoice_id, db)
    total         = Decimal(str(invoice.total_amount))

    invoice.paid_amount    = total_matched
    invoice.payment_status = (
        "PAID"           if total_matched >= total else
        "PARTIALLY_PAID" if total_matched > 0     else
        "UNPAID"
    )
    await db.flush()


async def _save_failed_match(payment_id: int, reason: str, db: AsyncSession) -> None:
    record = MatchingPaymentInvoice(
        payment_detail_id = payment_id,
        invoice_id        = None,
        matched_amount    = Decimal("0.00"),
        amount_pending    = None,
        match_score       = Decimal("0.00"),
        match_status      = "FAILED",
        match_reason      = reason,
    )
    db.add(record)
    await db.flush()


async def run_matching_for_payment(payment_id: int, db: AsyncSession) -> list:
    result = await db.execute(select(PaymentDetail).where(PaymentDetail.id == payment_id))
    payment = result.scalar_one_or_none()
    if not payment:
        return []

    pay_amount    = Decimal(str(payment.payment_amount))
    remaining_pay = pay_amount
    records       = []

    invoice_no_raw = (payment.invoice_no or "").strip()
    if not invoice_no_raw:
        await _save_failed_match(
            payment_id,
            "Invoice number missing in payment. Flagged for manual review.",
            db,
        )
        await db.commit()
        return records

    invoice_nos = _extract_multiple_invoice_nos(invoice_no_raw)

    fully_paid_ids = (
        select(MatchingPaymentInvoice.invoice_id)
        .where(MatchingPaymentInvoice.match_status == "FULL")
    )
    candidates_result = await db.execute(
        select(InvoiceData).where(
            and_(
                InvoiceData.customer_id == payment.customer_id,
                InvoiceData.id.notin_(fully_paid_ids),
            )
        )
    )
    candidates = candidates_result.scalars().all()
    print("candidates......................",candidates)

    if not candidates:
        await _save_failed_match(
            payment_id,
            "No open invoices found for this customer.",
            db,
        )
        await db.commit()
        return records

    for invoice in candidates:
        if remaining_pay <= 0:
            break

        if payment.currency != invoice.currency:
            record = MatchingPaymentInvoice(
                payment_detail_id = payment.id,
                invoice_id        = invoice.id,
                matched_amount    = Decimal("0.00"),
                amount_pending    = Decimal(str(invoice.total_amount)),
                match_score       = Decimal("0.00"),
                match_status      = "FAILED",
                match_reason      = f"Currency mismatch. Invoice: {invoice.currency}, Payment: {payment.currency}.",
            )
            db.add(record)
            await db.flush()
            records.append(record)
            continue

        if await _is_duplicate(payment.id, invoice.id, db):
            record = MatchingPaymentInvoice(
                payment_detail_id = payment.id,
                invoice_id        = invoice.id,
                matched_amount    = Decimal("0.00"),
                amount_pending    = Decimal(str(invoice.total_amount)),
                match_score       = Decimal("0.00"),
                match_status      = "DUPLICATE",
                match_reason      = f"Duplicate payment detected. {invoice.invoice_number} already matched.",
            )
            db.add(record)
            await db.flush()
            records.append(record)
            continue

        already_matched = await _get_already_matched_amount(invoice.id, db)
        inv_remaining   = Decimal(str(invoice.total_amount)) - already_matched

        if inv_remaining <= 0:
            continue

        score   = 0
        reasons = []
        inv_num = _normalize(invoice.invoice_number or "")

        invoice_no_match   = any(n == inv_num for n in invoice_nos)
        invoice_no_partial = any(inv_num in n or n in inv_num for n in invoice_nos)

        if invoice_no_match:
            score += 50
            reasons.append("Invoice number matched exactly.")
        elif invoice_no_partial:
            score += 40
            reasons.append("Invoice number partially matched.")
        else:
            reasons.append("Invoice number not found in payment.")

        if payment.customer_id == invoice.customer_id:
            score += 25
            reasons.append("Customer matched.")

        if payment.currency == invoice.currency:
            score += 10

        diff = abs(remaining_pay - inv_remaining)

        if remaining_pay == inv_remaining:
            score += 15
            reasons.append("Amount matched exactly.")
        elif diff <= ROUNDING_TOLERANCE:
            score += 15
            reasons.append(f"Amount matched within rounding tolerance (±₹{ROUNDING_TOLERANCE}).")
        elif remaining_pay < inv_remaining:
            score += 5
            reasons.append(f"Partial amount received. Pending: ₹{inv_remaining - remaining_pay:.2f}.")
        elif remaining_pay > inv_remaining:
            reasons.append(f"Overpayment. Invoice: ₹{inv_remaining:.2f}, Paid: ₹{remaining_pay:.2f}.")

      
        if already_matched > 0 and diff == Decimal("0.00"):
            score += 10
            reasons.append("Amount exactly closes outstanding balance on partially paid invoice.")

        score = min(score, 100)

       
        if score < 50:
            await _save_failed_match(
                payment_id,
                f"Low confidence match (score: {score}). " + " ".join(reasons),
                db,
            )
            continue

        allocatable = min(remaining_pay, inv_remaining)

        if remaining_pay > inv_remaining + ROUNDING_TOLERANCE:
            match_status   = "OVERPAYMENT"
            matched_amount = inv_remaining
            amount_pending = Decimal("0.00")
            excess         = remaining_pay - inv_remaining
            reasons.append(f"Excess amount ₹{excess:.2f} flagged for review.")

        elif diff <= ROUNDING_TOLERANCE or remaining_pay >= inv_remaining:
            match_status   = "FULL"
            matched_amount = inv_remaining
            amount_pending = Decimal("0.00")

        else:
            match_status   = "PARTIAL"
            matched_amount = allocatable
            amount_pending = inv_remaining - matched_amount

        record = MatchingPaymentInvoice(
            payment_detail_id = payment.id,
            invoice_id        = invoice.id,
            matched_amount    = matched_amount,
            amount_pending    = amount_pending,
            match_score       = Decimal(str(score)),
            match_status      = match_status,
            match_reason      = " ".join(reasons),
        )
        db.add(record)
        await db.flush()
        records.append(record)
        remaining_pay -= matched_amount

    if remaining_pay > 0 and records:
        await _save_failed_match(
            payment_id,
            f"₹{remaining_pay:.2f} of payment could not be matched to any invoice.",
            db,
        )

    matched_invoice_ids = {
        r.invoice_id for r in records
        if r.invoice_id and r.match_status in ["FULL", "PARTIAL", "OVERPAYMENT"]
    }
    for invoice_id in matched_invoice_ids:
        await _update_invoice_status(invoice_id, db)

    await db.commit()
    return records