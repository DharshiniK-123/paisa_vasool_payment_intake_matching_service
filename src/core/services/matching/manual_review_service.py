import logging
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.enums import MatchStatus
from src.data.models.postgres.invoice_data import InvoiceData
from src.data.models.postgres.matching_payment_invoice import MatchingPaymentInvoice
from src.data.models.postgres.payment_detail import PaymentDetail

from .db_writer import (
    get_already_matched_amount,
    save_failed_match,
    save_successful_match,
    update_invoice_status,
)
from .resolver import resolve_match, build_status_sentence

logger = logging.getLogger(__name__)

ZERO = Decimal("0.00")


async def _get_suggested_record(
    match_id:   int,
    payment_id: int,
    db:         AsyncSession,
) -> MatchingPaymentInvoice:
    """Fetch a SUGGESTED match record, raising 404/409 if not found or wrong state."""
    result = await db.execute(
        select(MatchingPaymentInvoice).where(
            MatchingPaymentInvoice.id               == match_id,
            MatchingPaymentInvoice.payment_detail_id == payment_id,
        )
    )
    record = result.scalar_one_or_none()

    if not record:
        raise HTTPException(
            status_code=404,
            detail=f"Match record {match_id} not found for payment {payment_id}.",
        )

    if record.match_status != MatchStatus.SUGGESTED:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Match record {match_id} is in status '{record.match_status}' "
                "and cannot be reviewed. Only SUGGESTED records can be approved or rejected."
            ),
        )

    return record


async def approve_match(
    match_id:   int,
    payment_id: int,
    db:         AsyncSession,
) -> MatchingPaymentInvoice:
    """
    Approve a SUGGESTED match.

    - Recalculates amounts against current invoice balance (may have changed).
    - Resolves to FULL / PARTIAL / OVERPAYMENT using existing resolver.
    - Updates invoice payment status.
    - Deletes the SUGGESTED record and creates a proper match record.
    """
    suggested = await _get_suggested_record(match_id, payment_id, db)

    # Fetch payment
    pay_result = await db.execute(
        select(PaymentDetail).where(PaymentDetail.id == payment_id)
    )
    payment = pay_result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail=f"Payment {payment_id} not found.")

    # Fetch invoice
    inv_result = await db.execute(
        select(InvoiceData).where(
            InvoiceData.id == suggested.invoice_id,
            InvoiceData.is_deleted.is_(False),
        )
    )
    invoice = inv_result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(
            status_code=404,
            detail=f"Invoice {suggested.invoice_id} not found or has been deleted.",
        )

    # Recalculate against current invoice balance
    already_matched = await get_already_matched_amount(int(invoice.id), db)
    inv_remaining   = Decimal(str(invoice.total_amount)) - already_matched
    remaining_pay   = Decimal(str(payment.payment_amount))

    if inv_remaining <= ZERO:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Invoice '{invoice.invoice_number}' has been fully paid since this "
                "suggestion was created. Please reject and manually assign to another invoice."
            ),
        )

    match_status, matched_amount, amount_pending = resolve_match(remaining_pay, inv_remaining)

    status_sentence = build_status_sentence(
        match_status=match_status,
        invoice=invoice,
        payment=payment,
        matched_amount=matched_amount,
        amount_pending=amount_pending,
        remaining_pay=remaining_pay,
        inv_remaining=inv_remaining,
    )

    # Delete SUGGESTED record
    await db.delete(suggested)
    await db.flush()

    # Save confirmed match
    record = await save_successful_match(
        payment_id=payment_id,
        invoice_id=int(invoice.id),
        matched_amount=matched_amount,
        amount_pending=amount_pending,
        score=int(suggested.match_score),
        match_status=match_status,
        match_reason=(
            f"Manually approved deep match. "
            f"Original suggestion score: {suggested.match_score}/60. "
            + status_sentence
        ),
        db=db,
    )

    await update_invoice_status(int(invoice.id), db)
    await db.commit()

    logger.info(
        "match_approved",
        extra={
            "payment_id": payment_id,
            "match_id":   match_id,
            "invoice_id": invoice.id,
            "status":     match_status,
        },
    )

    return record


async def reject_match(
    match_id:   int,
    payment_id: int,
    db:         AsyncSession,
) -> MatchingPaymentInvoice:
    """
    Reject a SUGGESTED match.

    - Marks the record as FAILED with a clear reason.
    - Does NOT re-run deep match — leaves payment as FAILED for manual assignment.
    """
    suggested = await _get_suggested_record(match_id, payment_id, db)

    suggested.match_status = MatchStatus.FAILED                     
    suggested.match_reason = (                                      
        f"Deep match suggestion rejected. "
        f"Original suggested invoice ID: {suggested.invoice_id}. "
        "Payment requires manual assignment."
    )
    suggested.invoice_id = None                                    

    await db.flush()
    await db.commit()

    logger.info(
        "match_rejected",
        extra={"payment_id": payment_id, "match_id": match_id},
    )

    return suggested
