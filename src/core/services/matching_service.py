from decimal import Decimal
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.utils.normalize import _normalize
from src.utils.extract_multiple_invoice_nos import _extract_multiple_invoice_nos
from src.utils.fx_client import get_exchange_rate
from src.data.models.postgres.invoice_data import InvoiceData
from src.data.models.postgres.payment_detail import PaymentDetail
from src.data.models.postgres.matching_payment_invoice import MatchingPaymentInvoice

ROUNDING_TOLERANCE = Decimal("1.00")
MIN_MATCH_SCORE    = 50

W_INV_EXACT    = 50
W_INV_PARTIAL  = 30
W_CUSTOMER     = 25
W_AMT_EXACT    = 20
W_AMT_TOLERANC = 15
W_AMT_PARTIAL  = 5
W_CURRENCY     = 5


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


async def _payment_already_processed(payment_id: int, db: AsyncSession) -> bool:
    result = await db.execute(
        select(func.count(MatchingPaymentInvoice.id))
        .where(
            and_(
                MatchingPaymentInvoice.payment_detail_id == payment_id,
                MatchingPaymentInvoice.match_status.in_(["FULL", "PARTIAL", "OVERPAYMENT"]),
            )
        )
    )
    return (result.scalar() or 0) > 0


async def _is_duplicate(payment_id: int, invoice_id: int, db: AsyncSession) -> bool:
    result = await db.execute(
        select(func.count(MatchingPaymentInvoice.id))
        .where(
            and_(
                MatchingPaymentInvoice.payment_detail_id == payment_id,
                MatchingPaymentInvoice.invoice_id        == invoice_id,
                MatchingPaymentInvoice.match_status.in_(["FULL", "PARTIAL", "OVERPAYMENT"]),
            )
        )
    )
    return (result.scalar() or 0) > 0


async def _update_invoice_status(invoice_id: int, db: AsyncSession) -> None:
    result = await db.execute(
        select(InvoiceData).where(
            InvoiceData.id         == invoice_id,
            InvoiceData.is_deleted.is_(False),
        )
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        return

    total_matched = await _get_already_matched_amount(invoice_id, db)
    total         = Decimal(str(invoice.total_amount))

    invoice.paid_amount    = total_matched
    invoice.payment_status = (
        "PAID"           if total_matched >= total else
        "PARTIALLY_PAID" if total_matched >  0     else
        "UNPAID"
    )
    await db.flush()


async def _save_failed_match(
    payment_id: int,
    reason: str,
    db: AsyncSession,
    invoice_id: int | None = None,
    score: int = 0,
) -> MatchingPaymentInvoice:
    record = MatchingPaymentInvoice(
        payment_detail_id=payment_id,
        invoice_id=invoice_id,
        matched_amount=Decimal("0.00"),
        amount_pending=None,
        match_score=Decimal(str(score)),
        match_status="FAILED",
        match_reason=reason,
    )
    db.add(record)
    await db.flush()
    return record


def _score_invoice(
    payment,
    invoice,
    invoice_nos: list[str],
    remaining_pay: Decimal,
    inv_remaining: Decimal,
    converted: bool = False,
    fx_rate: Decimal | None = None,
    original_pay_amount: Decimal | None = None,
) -> tuple[int, list[str]]:
    score   = 0
    reasons = []

    inv_num = _normalize(invoice.invoice_number or "")

    exact_hit   = any(n == inv_num for n in invoice_nos)
    partial_hit = (not exact_hit) and any(inv_num in n or n in inv_num for n in invoice_nos)

    if exact_hit:
        score += W_INV_EXACT
        reasons.append(f"Invoice number '{invoice.invoice_number}' matched exactly.")
    elif partial_hit:
        score += W_INV_PARTIAL
        reasons.append(
            f"Invoice number '{invoice.invoice_number}' partially matched "
            f"the payment reference '{payment.invoice_no}'."
        )

    if payment.customer_id == invoice.customer_id:
        score += W_CUSTOMER
        reasons.append("Customer ID matches between payment and invoice.")
    else:
        reasons.append(
            f"Customer ID mismatch — payment customer: {payment.customer_id}, "
            f"invoice customer: {invoice.customer_id}."
        )

    if converted and fx_rate is not None and original_pay_amount is not None:
        score += W_CURRENCY
        reasons.append(
            f"Currency mismatch resolved via automatic conversion: "
            f"payment currency {payment.currency} -> invoice currency {invoice.currency}. "
            f"Exchange rate applied on payment date ({payment.paid_date}): "
            f"1 {payment.currency} = {fx_rate:.8f} {invoice.currency}. "
            f"Original payment amount: {payment.currency} {original_pay_amount:,.2f} "
            f"converted to {invoice.currency} {remaining_pay:,.2f}."
        )
    else:
        score += W_CURRENCY

    diff = abs(remaining_pay - inv_remaining)

    if remaining_pay == inv_remaining:
        score += W_AMT_EXACT
        reasons.append(
            f"{'Converted payment' if converted else 'Payment'} amount "
            f"({invoice.currency} {remaining_pay:,.2f}) matches the outstanding invoice "
            "balance exactly."
        )
    elif diff <= ROUNDING_TOLERANCE:
        score += W_AMT_TOLERANC
        reasons.append(
            f"{'Converted payment' if converted else 'Payment'} amount "
            f"({invoice.currency} {remaining_pay:,.2f}) matches the outstanding balance "
            f"within the rounding tolerance (+-{ROUNDING_TOLERANCE})."
        )
    elif remaining_pay < inv_remaining:
        score += W_AMT_PARTIAL
        shortfall = inv_remaining - remaining_pay
        reasons.append(
            f"Partial payment received. "
            f"{'Converted payment' if converted else 'Payment'}: "
            f"{invoice.currency} {remaining_pay:,.2f}, "
            f"Invoice outstanding: {invoice.currency} {inv_remaining:,.2f}. "
            f"Shortfall: {invoice.currency} {shortfall:,.2f}."
        )
    else:
        excess = remaining_pay - inv_remaining
        score += W_AMT_PARTIAL
        reasons.append(
            f"{'Converted payment' if converted else 'Payment'} "
            f"({invoice.currency} {remaining_pay:,.2f}) exceeds the invoice "
            f"outstanding balance ({invoice.currency} {inv_remaining:,.2f}) "
            f"by {invoice.currency} {excess:,.2f}."
        )

    already_matched = Decimal(str(invoice.total_amount)) - inv_remaining
    if already_matched > 0 and diff == Decimal("0.00"):
        score += 10
        reasons.append(
            f"Payment closes the remaining balance on a partially-paid invoice "
            f"(previously paid: {invoice.currency} {already_matched:,.2f})."
        )

    return min(score, 100), reasons


def _resolve_match(
    remaining_pay: Decimal,
    inv_remaining: Decimal,
) -> tuple[str, Decimal, Decimal]:
    diff = abs(remaining_pay - inv_remaining)
    if remaining_pay > inv_remaining + ROUNDING_TOLERANCE:
        return "OVERPAYMENT", inv_remaining, Decimal("0.00")
    if diff <= ROUNDING_TOLERANCE or remaining_pay >= inv_remaining:
        return "FULL", inv_remaining, Decimal("0.00")
    return "PARTIAL", remaining_pay, inv_remaining - remaining_pay


async def run_matching_for_payment(payment_id: int, db: AsyncSession) -> list:
    if await _payment_already_processed(payment_id, db):
        result = await db.execute(
            select(MatchingPaymentInvoice)
            .where(MatchingPaymentInvoice.payment_detail_id == payment_id)
        )
        return result.scalars().all()

    result = await db.execute(
        select(PaymentDetail).where(
            PaymentDetail.id         == payment_id,
            PaymentDetail.is_deleted.is_(False),
        )
    )
    payment = result.scalar_one_or_none()
    if not payment:
        return []

    pay_amount    = Decimal(str(payment.payment_amount))
    remaining_pay = pay_amount
    records: list[MatchingPaymentInvoice] = []

    if pay_amount <= Decimal("0.00"):
        rec = await _save_failed_match(
            payment_id,
            f"Payment amount is {payment.currency} {pay_amount:,.2f}, which is not a valid "
            "amount. Payments must be greater than zero. This record requires manual review.",
            db,
        )
        records.append(rec)
        await db.commit()
        return records

    invoice_no_raw = (payment.invoice_no or "").strip()
    if not invoice_no_raw:
        rec = await _save_failed_match(
            payment_id,
            "No invoice number was provided with this payment. "
            "The payment cannot be automatically matched and requires manual review.",
            db,
        )
        records.append(rec)
        await db.commit()
        return records

    invoice_nos = _extract_multiple_invoice_nos(invoice_no_raw)

    fully_paid_ids_subq = (
        select(MatchingPaymentInvoice.invoice_id)
        .where(MatchingPaymentInvoice.match_status == "FULL")
    )

    candidates_result = await db.execute(
        select(InvoiceData).where(
            and_(
                InvoiceData.customer_id == payment.customer_id,
                InvoiceData.id.notin_(fully_paid_ids_subq),
                InvoiceData.is_deleted.is_(False),
            )
        )
    )
    all_candidates: list[InvoiceData] = candidates_result.scalars().all()

    already_paid_result = await db.execute(
        select(InvoiceData).where(
            and_(
                InvoiceData.customer_id == payment.customer_id,
                InvoiceData.id.in_(fully_paid_ids_subq),
                InvoiceData.is_deleted.is_(False),
            )
        )
    )
    already_paid_invoices: list[InvoiceData] = already_paid_result.scalars().all()

    deleted_result = await db.execute(
        select(InvoiceData).where(
            and_(
                InvoiceData.customer_id == payment.customer_id,
                InvoiceData.is_deleted.is_(True),
            )
        )
    )
    deleted_invoices: list[InvoiceData] = deleted_result.scalars().all()

    if not all_candidates:
        for inv in already_paid_invoices:
            inv_num = _normalize(inv.invoice_number or "")
            if any(n == inv_num or inv_num in n or n in inv_num for n in invoice_nos):
                rec = await _save_failed_match(
                    payment_id,
                    f"Invoice '{inv.invoice_number}' has already been fully paid by a "
                    "previous payment. This payment cannot be applied to it again. "
                    "Please verify whether a duplicate payment was made.",
                    db,
                    invoice_id=inv.id,
                )
                records.append(rec)
                await db.commit()
                return records

        for inv in deleted_invoices:
            inv_num = _normalize(inv.invoice_number or "")
            if any(n == inv_num or inv_num in n or n in inv_num for n in invoice_nos):
                rec = await _save_failed_match(
                    payment_id,
                    f"Invoice '{inv.invoice_number}' exists but has been deleted/archived "
                    "and cannot receive payments. Please contact your finance team to "
                    "restore the invoice or redirect this payment.",
                    db,
                    invoice_id=inv.id,
                )
                records.append(rec)
                await db.commit()
                return records

        rec = await _save_failed_match(
            payment_id,
            f"No open invoices were found for customer ID {payment.customer_id}. "
            "Either all invoices are already fully paid, or the customer ID does not "
            "match any invoice on record.",
            db,
        )
        records.append(rec)
        await db.commit()
        return records

    matched_candidates:  list[InvoiceData] = []
    currency_mismatches: list[InvoiceData] = []

    for inv in all_candidates:
        inv_num    = _normalize(inv.invoice_number or "")
        number_hit = any(n == inv_num or inv_num in n or n in inv_num for n in invoice_nos)
        if not number_hit:
            continue
        if payment.currency != inv.currency:
            currency_mismatches.append(inv)
        else:
            matched_candidates.append(inv)

    if not matched_candidates and not currency_mismatches:
        for inv in already_paid_invoices:
            inv_num = _normalize(inv.invoice_number or "")
            if any(n == inv_num or inv_num in n or n in inv_num for n in invoice_nos):
                rec = await _save_failed_match(
                    payment_id,
                    f"Invoice '{inv.invoice_number}' has already been fully paid by a "
                    "previous payment. This payment cannot be applied to it again. "
                    "Please verify whether a duplicate payment was made.",
                    db,
                    invoice_id=inv.id,
                )
                records.append(rec)
                await db.commit()
                return records

        for inv in deleted_invoices:
            inv_num = _normalize(inv.invoice_number or "")
            if any(n == inv_num or inv_num in n or n in inv_num for n in invoice_nos):
                rec = await _save_failed_match(
                    payment_id,
                    f"Invoice '{inv.invoice_number}' exists but has been deleted/archived "
                    "and cannot receive payments. Please contact your finance team to "
                    "restore the invoice or redirect this payment.",
                    db,
                    invoice_id=inv.id,
                )
                records.append(rec)
                await db.commit()
                return records

        rec = await _save_failed_match(
            payment_id,
            f"None of the invoice number(s) in the payment reference "
            f"({payment.invoice_no}) could be matched to an open invoice for "
            f"customer ID {payment.customer_id}. "
            "Please verify the invoice number and customer details.",
            db,
        )
        records.append(rec)
        await db.commit()
        return records

    for invoice in matched_candidates:
        if remaining_pay <= Decimal("0.00"):
            break

        if await _is_duplicate(payment.id, invoice.id, db):
            rec = MatchingPaymentInvoice(
                payment_detail_id=payment.id,
                invoice_id=invoice.id,
                matched_amount=Decimal("0.00"),
                amount_pending=Decimal(str(invoice.total_amount)),
                match_score=Decimal("0.00"),
                match_status="DUPLICATE",
                match_reason=(
                    f"This payment has already been matched to invoice "
                    f"'{invoice.invoice_number}'. "
                    "Creating a second match record would result in double-counting."
                ),
            )
            db.add(rec)
            await db.flush()
            records.append(rec)
            continue

        already_matched = await _get_already_matched_amount(invoice.id, db)
        inv_remaining   = Decimal(str(invoice.total_amount)) - already_matched
        if inv_remaining <= Decimal("0.00"):
            continue

        score, reasons = _score_invoice(
            payment, invoice, invoice_nos, remaining_pay, inv_remaining
        )

        if score < MIN_MATCH_SCORE:
            rec = await _save_failed_match(
                payment_id,
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
            records.append(rec)
            continue

        match_status, matched_amount, amount_pending = _resolve_match(
            remaining_pay, inv_remaining
        )

        status_sentence = {
            "FULL": (
                f"Invoice '{invoice.invoice_number}' has been fully matched. "
                f"Amount applied: {payment.currency} {matched_amount:,.2f}."
            ),
            "PARTIAL": (
                f"Invoice '{invoice.invoice_number}' has been partially matched. "
                f"Amount applied: {payment.currency} {matched_amount:,.2f}. "
                f"Outstanding balance remaining: {invoice.currency} {amount_pending:,.2f}."
            ),
            "OVERPAYMENT": (
                f"Invoice '{invoice.invoice_number}' has been fully matched but the payment "
                f"exceeds the invoice amount. "
                f"Amount applied: {invoice.currency} {matched_amount:,.2f}. "
                f"Excess amount: {payment.currency} {remaining_pay - inv_remaining:,.2f} "
                "— flagged for review."
            ),
        }[match_status]

        rec = MatchingPaymentInvoice(
            payment_detail_id=payment.id,
            invoice_id=invoice.id,
            matched_amount=matched_amount,
            amount_pending=amount_pending,
            match_score=Decimal(str(score)),
            match_status=match_status,
            match_reason=" ".join(reasons) + " " + status_sentence,
        )
        db.add(rec)
        await db.flush()
        records.append(rec)
        remaining_pay -= matched_amount

    for invoice in currency_mismatches:
        if remaining_pay <= Decimal("0.00"):
            break

        if await _is_duplicate(payment.id, invoice.id, db):
            rec = MatchingPaymentInvoice(
                payment_detail_id=payment.id,
                invoice_id=invoice.id,
                matched_amount=Decimal("0.00"),
                amount_pending=Decimal(str(invoice.total_amount)),
                match_score=Decimal("0.00"),
                match_status="DUPLICATE",
                match_reason=(
                    f"This payment has already been matched to invoice "
                    f"'{invoice.invoice_number}'. "
                    "Creating a second match record would result in double-counting."
                ),
            )
            db.add(rec)
            await db.flush()
            records.append(rec)
            continue

        try:
            fx_rate = await get_exchange_rate(
                payment.paid_date,
                payment.currency,
                invoice.currency,
                db,
            )
        except RuntimeError as exc:
            rec = await _save_failed_match(
                payment_id,
                f"Currency mismatch: payment is in {payment.currency} but invoice "
                f"'{invoice.invoice_number}' is in {invoice.currency}. "
                f"Automatic FX conversion failed: {exc}. Manual review required.",
                db,
                invoice_id=invoice.id,
            )
            records.append(rec)
            continue

        converted_remaining = (remaining_pay * fx_rate).quantize(Decimal("0.01"))

        already_matched = await _get_already_matched_amount(invoice.id, db)
        inv_remaining   = Decimal(str(invoice.total_amount)) - already_matched
        if inv_remaining <= Decimal("0.00"):
            continue

        score, reasons = _score_invoice(
            payment,
            invoice,
            invoice_nos,
            converted_remaining,
            inv_remaining,
            converted=True,
            fx_rate=fx_rate,
            original_pay_amount=remaining_pay,
        )

        if score < MIN_MATCH_SCORE:
            rec = await _save_failed_match(
                payment_id,
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
            records.append(rec)
            continue

        match_status, matched_amount, amount_pending = _resolve_match(
            converted_remaining, inv_remaining
        )

        status_sentence = {
            "FULL": (
                f"Invoice '{invoice.invoice_number}' fully matched after currency conversion. "
                f"Amount applied: {invoice.currency} {matched_amount:,.2f} "
                f"(equivalent to {payment.currency} "
                f"{(matched_amount / fx_rate).quantize(Decimal('0.01')):,.2f} "
                f"at rate 1 {payment.currency} = {fx_rate:.8f} {invoice.currency} "
                f"on {payment.paid_date})."
            ),
            "PARTIAL": (
                f"Invoice '{invoice.invoice_number}' partially matched after currency "
                f"conversion. Amount applied: {invoice.currency} {matched_amount:,.2f}. "
                f"Outstanding balance remaining: {invoice.currency} {amount_pending:,.2f}."
            ),
            "OVERPAYMENT": (
                f"Invoice '{invoice.invoice_number}' fully matched after currency conversion "
                f"but converted payment exceeds the invoice amount. "
                f"Amount applied: {invoice.currency} {matched_amount:,.2f}. "
                f"Converted excess: {invoice.currency} "
                f"{converted_remaining - inv_remaining:,.2f} — flagged for review."
            ),
        }[match_status]

        rec = MatchingPaymentInvoice(
            payment_detail_id=payment.id,
            invoice_id=invoice.id,
            matched_amount=matched_amount,
            amount_pending=amount_pending,
            match_score=Decimal(str(score)),
            match_status=match_status,
            match_reason=" ".join(reasons) + " " + status_sentence,
        )
        db.add(rec)
        await db.flush()
        records.append(rec)
        
        consumed_pay_ccy = (matched_amount / fx_rate).quantize(Decimal("0.01"))
        remaining_pay   -= consumed_pay_ccy

    last_successful_status = next(
        (r.match_status for r in reversed(records)
         if r.match_status in ("FULL", "PARTIAL", "OVERPAYMENT")),
        None,
    )
    overpayment_fully_absorbed = (
        last_successful_status == "OVERPAYMENT"
        and remaining_pay > Decimal("0.00")
    )

    if remaining_pay > Decimal("0.00") and not overpayment_fully_absorbed:
        successful = [
            r for r in records
            if r.match_status in ("FULL", "PARTIAL", "OVERPAYMENT")
        ]
        if successful:
            applied_invoices = ", ".join(f"'{r.invoice_id}'" for r in successful)
            reason = (
                f"{payment.currency} {remaining_pay:,.2f} of the payment could not be "
                f"matched to any invoice after applying amounts to invoice(s) "
                f"{applied_invoices}. The remaining amount requires manual review."
            )
        else:
            reason = (
                f"The full payment amount of {payment.currency} {pay_amount:,.2f} "
                "could not be matched to any open invoice. "
                "Please verify the invoice number and customer details."
            )
        rec = await _save_failed_match(payment_id, reason, db)
        records.append(rec)

    matched_invoice_ids = {
        r.invoice_id for r in records
        if r.invoice_id and r.match_status in ("FULL", "PARTIAL", "OVERPAYMENT")
    }
    for invoice_id in matched_invoice_ids:
        await _update_invoice_status(invoice_id, db)

    await db.commit()
    return records
