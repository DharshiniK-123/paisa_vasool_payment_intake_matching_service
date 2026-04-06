import logging
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.enums import InvoicePaymentStatus, MatchStatus
from src.data.models.postgres.invoice_data import InvoiceData
from src.data.models.postgres.matching_payment_invoice import MatchingPaymentInvoice

logger = logging.getLogger(__name__)

CONCLUSIVE_STATUSES = (
    MatchStatus.FULL,
    MatchStatus.PARTIAL,
    MatchStatus.OVERPAYMENT,
    MatchStatus.MANUALLY_MATCHED,
)

REVIEW_STATUSES = (MatchStatus.SUGGESTED,)


async def get_already_matched_amount(invoice_id: int, db: AsyncSession) -> Decimal:
    result = await db.execute(
        select(func.coalesce(func.sum(MatchingPaymentInvoice.matched_amount), 0))
        .where(
            and_(
                MatchingPaymentInvoice.invoice_id == invoice_id,
                MatchingPaymentInvoice.match_status.in_(CONCLUSIVE_STATUSES),
            )
        )
    )
    return Decimal(str(result.scalar()))


async def is_duplicate(payment_id: int, invoice_id: int, db: AsyncSession) -> bool:
    result = await db.execute(
        select(func.count(MatchingPaymentInvoice.id))
        .where(
            and_(
                MatchingPaymentInvoice.payment_detail_id == payment_id,
                MatchingPaymentInvoice.invoice_id        == invoice_id,
                MatchingPaymentInvoice.match_status.in_(CONCLUSIVE_STATUSES),
            )
        )
    )
    return (result.scalar() or 0) > 0


async def payment_already_processed(payment_id: int, db: AsyncSession) -> bool:
    """
    Returns True if this payment already has a conclusive or pending-review record.
    Prevents re-running the pipeline on payments that are already matched or
    awaiting manual review.
    """
    result = await db.execute(
        select(func.count(MatchingPaymentInvoice.id))
        .where(
            and_(
                MatchingPaymentInvoice.payment_detail_id == payment_id,
                MatchingPaymentInvoice.match_status.in_(
                    list(CONCLUSIVE_STATUSES) + list(REVIEW_STATUSES)
                ),
            )
        )
    )
    return (result.scalar() or 0) > 0


async def fetch_existing_records(payment_id: int, db: AsyncSession) -> list[MatchingPaymentInvoice]:
    result = await db.execute(
        select(MatchingPaymentInvoice)
        .where(MatchingPaymentInvoice.payment_detail_id == payment_id)
    )
    return list(result.scalars().all())


async def save_failed_match(
    payment_id: int,
    reason:     str,
    db:         AsyncSession,
    invoice_id: int | None = None,
    score:      int        = 0,
) -> MatchingPaymentInvoice:
    record = MatchingPaymentInvoice(
        payment_detail_id=payment_id,
        invoice_id=invoice_id,
        matched_amount=Decimal("0.00"),
        amount_pending=None,
        match_score=Decimal(str(score)),
        match_status=MatchStatus.FAILED,
        match_reason=reason,
    )
    db.add(record)
    await db.flush()
    logger.info(
        "match_failed",
        extra={"payment_id": payment_id, "invoice_id": invoice_id, "reason": reason[:120]},
    )
    return record


async def save_suggested_match(
    payment_id:     int,
    invoice_id:     int,
    matched_amount: Decimal,
    amount_pending: Decimal,
    score:          int,
    match_reason:   str,
    db:             AsyncSession,
) -> MatchingPaymentInvoice:
    """
    Saves a SUGGESTED match — deep match found a likely candidate but
    confidence is not high enough to auto-apply. Requires human approval.
    """
    record = MatchingPaymentInvoice(
        payment_detail_id=payment_id,
        invoice_id=invoice_id,
        matched_amount=matched_amount,
        amount_pending=amount_pending,
        match_score=Decimal(str(score)),
        match_status=MatchStatus.SUGGESTED,
        match_reason=match_reason,
    )
    db.add(record)
    await db.flush()
    logger.info(
        "match_suggested",
        extra={
            "payment_id":  payment_id,
            "invoice_id":  invoice_id,
            "score":       score,
            "matched_amt": str(matched_amount),
        },
    )
    return record


async def save_duplicate_match(
    payment_id: int,
    invoice:    InvoiceData,
    db:         AsyncSession,
) -> MatchingPaymentInvoice:
    record = MatchingPaymentInvoice(
        payment_detail_id=payment_id,
        invoice_id=invoice.id,
        matched_amount=Decimal("0.00"),
        amount_pending=Decimal(str(invoice.total_amount)),
        match_score=Decimal("0.00"),
        match_status=MatchStatus.DUPLICATE,
        match_reason=(
            f"This payment has already been matched to invoice '{invoice.invoice_number}'. "
            "Creating a second match record would result in double-counting."
        ),
    )
    db.add(record)
    await db.flush()
    return record


async def save_successful_match(
    payment_id:    int,
    invoice_id:    int,
    matched_amount: Decimal,
    amount_pending: Decimal,
    score:          int,
    match_status:   str,
    match_reason:   str,
    db:             AsyncSession,
) -> MatchingPaymentInvoice:
    record = MatchingPaymentInvoice(
        payment_detail_id=payment_id,
        invoice_id=invoice_id,
        matched_amount=matched_amount,
        amount_pending=amount_pending,
        match_score=Decimal(str(score)),
        match_status=match_status,
        match_reason=match_reason,
    )
    db.add(record)
    await db.flush()
    logger.info(
        "match_saved",
        extra={
            "payment_id":  payment_id,
            "invoice_id":  invoice_id,
            "status":      match_status,
            "score":       score,
            "matched_amt": str(matched_amount),
        },
    )
    return record


async def update_invoice_status(invoice_id: int, db: AsyncSession) -> None:
    result = await db.execute(
        select(InvoiceData).where(
            InvoiceData.id == invoice_id,
            InvoiceData.is_deleted.is_(False),
        )
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        return

    has_overpayment_result = await db.execute(
        select(func.count(MatchingPaymentInvoice.id)).where(
            and_(
                MatchingPaymentInvoice.invoice_id   == invoice_id,
                MatchingPaymentInvoice.match_status == MatchStatus.OVERPAYMENT,
            )
        )
    )
    has_overpayment = (has_overpayment_result.scalar() or 0) > 0

    total_matched           = await get_already_matched_amount(invoice_id, db)
    total                   = Decimal(str(invoice.total_amount))
    invoice.paid_amount     = total_matched  # type: ignore[assignment]

    if has_overpayment or total_matched > total:
        invoice.payment_status = InvoicePaymentStatus.OVERPAID       # type: ignore[assignment]
    elif total_matched == total:
        invoice.payment_status = InvoicePaymentStatus.PAID           # type: ignore[assignment]
    elif total_matched > 0:
        invoice.payment_status = InvoicePaymentStatus.PARTIALLY_PAID # type: ignore[assignment]
    else:
        invoice.payment_status = InvoicePaymentStatus.UNPAID         # type: ignore[assignment]

    await db.flush()
