from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.enums import InvoicePaymentStatus, MatchStatus
from src.data.models.postgres.customer import Customer
from src.data.models.postgres.invoice_data import InvoiceData
from src.data.models.postgres.matching_payment_invoice import MatchingPaymentInvoice
from src.data.models.postgres.payment_detail import PaymentDetail

ACTIVE_PAYMENT = PaymentDetail.is_deleted.is_(False)
ACTIVE_INVOICE = InvoiceData.is_deleted.is_(False)


async def get_matches_by_payment_id(
        payment_id: int,
        db: AsyncSession) -> list[MatchingPaymentInvoice]:

    result = await db.execute(
        select(MatchingPaymentInvoice)
        .where(MatchingPaymentInvoice.payment_detail_id == payment_id)
        .order_by(MatchingPaymentInvoice.created_at.desc())
    )
    return list(result.scalars().all())


async def get_matches_by_invoice_id(
        invoice_id: int,
        db: AsyncSession) -> list[MatchingPaymentInvoice]:

    result = await db.execute(
        select(MatchingPaymentInvoice)
        .where(MatchingPaymentInvoice.invoice_id == invoice_id)
        .order_by(MatchingPaymentInvoice.created_at.desc())
    )
    return list(result.scalars().all())


async def get_all_matches(db: AsyncSession) -> list[MatchingPaymentInvoice]:
    result = await db.execute(
        select(MatchingPaymentInvoice).order_by(MatchingPaymentInvoice.created_at.desc())
    )
    return list(result.scalars().all())


async def get_unmatched_payments(db: AsyncSession) -> list:
    matched_ids = select(MatchingPaymentInvoice.payment_detail_id).where(
        MatchingPaymentInvoice.match_status.in_([
            MatchStatus.FULL,
            MatchStatus.PARTIAL,
            MatchStatus.OVERPAYMENT,
        ])
    )
    result = await db.execute(
        select(
            PaymentDetail.id,
            PaymentDetail.document_id,
            PaymentDetail.customer_id,
            PaymentDetail.invoice_no,
            PaymentDetail.payment_amount.label("amount"),
            PaymentDetail.currency,
            PaymentDetail.paid_date.label("payment_date"),
            PaymentDetail.payment_reference.label("reference_number"),
            Customer.name.label("payer_name"),
            Customer.email.label("payer_email"),
        )
        .join(Customer, PaymentDetail.customer_id == Customer.id, isouter=True)
        .where(PaymentDetail.id.notin_(matched_ids), ACTIVE_PAYMENT)
    )
    return list(result.mappings().all())


async def get_unmatched_invoices(db: AsyncSession) -> list:
    result = await db.execute(
        select(
            InvoiceData,
            Customer.name.label("customer_name"),
            Customer.email.label("customer_email"),
        )
        .join(Customer, InvoiceData.customer_id == Customer.id, isouter=True)
        .where(InvoiceData.payment_status == InvoicePaymentStatus.UNPAID, ACTIVE_INVOICE)
    )
    return list(result.all())


async def get_invoice_detail(invoice_id: int, db: AsyncSession):
    result = await db.execute(
        select(
            InvoiceData,
            Customer.name.label("customer_name"),
            Customer.email.label("customer_email"),
        )
        .join(Customer, InvoiceData.customer_id == Customer.id, isouter=True)
        .where(InvoiceData.id == invoice_id, ACTIVE_INVOICE)
    )
    return result.first()


async def get_payment_detail(payment_id: int, db: AsyncSession):
    result = await db.execute(
        select(
            PaymentDetail,
            Customer.name.label("payer_name"),
            Customer.email.label("payer_email"),
        )
        .join(Customer, PaymentDetail.customer_id == Customer.id, isouter=True)
        .where(PaymentDetail.id == payment_id, ACTIVE_PAYMENT)
    )
    return result.first()


async def get_recent_matches(limit: int, db: AsyncSession) -> list[MatchingPaymentInvoice]:
    result = await db.execute(
        select(MatchingPaymentInvoice)
        .join(PaymentDetail, MatchingPaymentInvoice.payment_detail_id == PaymentDetail.id)
        .join(InvoiceData, MatchingPaymentInvoice.invoice_id == InvoiceData.id, isouter=True)
        .where(
            PaymentDetail.is_deleted.is_(False),
            or_(
                MatchingPaymentInvoice.invoice_id.is_(None),
                InvoiceData.is_deleted.is_(False),
            ),
        )
        .order_by(MatchingPaymentInvoice.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_discrepancies(db: AsyncSession) -> list:
    result = await db.execute(
        select(
            MatchingPaymentInvoice.id,
            MatchingPaymentInvoice.invoice_id,
            MatchingPaymentInvoice.match_status,
            MatchingPaymentInvoice.match_reason,
            MatchingPaymentInvoice.matched_amount,
            MatchingPaymentInvoice.created_at,
            PaymentDetail.invoice_no,
            PaymentDetail.payment_amount,
            PaymentDetail.currency,
            PaymentDetail.paid_date,
            Customer.name.label("payer_name"),
            Customer.email.label("payer_email"),
        )
        .join(PaymentDetail, MatchingPaymentInvoice.payment_detail_id == PaymentDetail.id)
        .join(Customer, PaymentDetail.customer_id == Customer.id, isouter=True)
        .where(
            MatchingPaymentInvoice.match_status.in_([
                MatchStatus.FAILED,
                MatchStatus.DUPLICATE,
                MatchStatus.PARTIAL,
                MatchStatus.OVERPAYMENT,
            ]),
            ACTIVE_PAYMENT,
        )
        .order_by(MatchingPaymentInvoice.created_at.desc())
    )
    return [dict(row) for row in result.mappings().all()]
