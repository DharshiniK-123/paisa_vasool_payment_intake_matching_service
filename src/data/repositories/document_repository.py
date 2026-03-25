from sqlalchemy import and_, select
from sqlalchemy import delete as sa_delete
from sqlalchemy import func as sqlfunc
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.customer import Customer
from src.data.models.postgres.document import Document
from src.data.models.postgres.invoice_data import InvoiceData
from src.data.models.postgres.matching_payment_invoice import MatchingPaymentInvoice
from src.data.models.postgres.payment_detail import PaymentDetail


async def get_document_by_id(document_id: int, db: AsyncSession) -> Document | None:
    result = await db.execute(select(Document).where(Document.id == document_id))
    return result.scalar_one_or_none()


async def get_all_documents(db: AsyncSession) -> list[Document]:
    result = await db.execute(select(Document))
    return list(result.scalars().all())  # fix 1

async def get_customer_by_email(email: str, db: AsyncSession) -> Customer | None:
    result = await db.execute(
        select(Customer).where(sqlfunc.lower(Customer.email) == email.lower())
    )
    return result.scalar_one_or_none()


async def get_customer_by_name(name: str, db: AsyncSession) -> Customer | None:
    result = await db.execute(
        select(Customer).where(sqlfunc.lower(Customer.name) == name.lower())
    )
    return result.scalar_one_or_none()


async def create_customer(
        db: AsyncSession,
        name: str,
        email: str,
        phone: str | None = None) -> Customer:

    customer = Customer(name=name, email=email, phone=phone)
    db.add(customer)
    await db.flush()
    return customer


async def find_duplicate_payment_reference(
    payment_reference: str, exclude_document_id: int, db: AsyncSession
):
    result = await db.execute(
        select(
            PaymentDetail.id,
            PaymentDetail.document_id,
            PaymentDetail.payment_reference,
        ).where(
            and_(
                PaymentDetail.payment_reference == payment_reference,
                PaymentDetail.is_deleted.is_(False),
                PaymentDetail.document_id != exclude_document_id,
            )
        )
    )
    return result.fetchone()


async def find_duplicate_invoice_number(
    invoice_number: str, exclude_document_id: int, db: AsyncSession
):
    result = await db.execute(
        select(
            InvoiceData.id,
            InvoiceData.document_id,
            InvoiceData.invoice_number,
        ).where(
            and_(
                InvoiceData.invoice_number == invoice_number,
                InvoiceData.is_deleted.is_(False),
                InvoiceData.document_id != exclude_document_id,
            )
        )
    )
    return result.fetchone()

async def get_invoices_with_matches(document_id: int, db: AsyncSession) -> list:
    result = await db.execute(
        select(
            InvoiceData,
            Customer.name.label("customer_name"),
            Customer.email.label("customer_email"),
            MatchingPaymentInvoice.id.label("match_id"),
            MatchingPaymentInvoice.match_status,
            MatchingPaymentInvoice.matched_amount,
            MatchingPaymentInvoice.amount_pending,
            MatchingPaymentInvoice.match_reason,
            MatchingPaymentInvoice.payment_detail_id,
            MatchingPaymentInvoice.created_at.label("matched_at"),
        )
        .join(Customer, InvoiceData.customer_id == Customer.id, isouter=True)
        .outerjoin(MatchingPaymentInvoice, MatchingPaymentInvoice.invoice_id == InvoiceData.id)
        .where(InvoiceData.document_id == document_id)
        .order_by(InvoiceData.id, MatchingPaymentInvoice.created_at.desc())
    )
    return list(result.all())  


async def get_payments_by_document(document_id: int, db: AsyncSession) -> list:
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
            Customer.phone.label("payer_phone"),
        )
        .join(Customer, PaymentDetail.customer_id == Customer.id, isouter=True)
        .where(
            PaymentDetail.document_id == document_id,
            PaymentDetail.is_deleted.is_(False), 
        )
    )
    return list(result.mappings().all())  



async def get_invoice_by_id(invoice_id: int, db: AsyncSession) -> InvoiceData | None:
    result = await db.execute(select(InvoiceData).where(InvoiceData.id == invoice_id))
    return result.scalar_one_or_none()


async def soft_delete_invoice(invoice_id: int, db: AsyncSession) -> None:
    result = await db.execute(select(InvoiceData).where(InvoiceData.id == invoice_id))
    invoice = result.scalar_one_or_none()
    if not invoice:
        return
    invoice.is_deleted = True  # type: ignore[assignment]

    matching_result = await db.execute(
        select(MatchingPaymentInvoice).where(
            MatchingPaymentInvoice.invoice_id == invoice_id,
            MatchingPaymentInvoice.match_status.in_(
                ["FULL", "PARTIAL", "OVERPAYMENT", "FAILED", "DUPLICATE"]
            ),
        )
    )
    matching_records = matching_result.scalars().all()
    affected_payment_ids = {r.payment_detail_id for r in matching_records}

    await db.execute(
        sa_delete(MatchingPaymentInvoice).where(
            MatchingPaymentInvoice.invoice_id == invoice_id,
        )
    )

    if affected_payment_ids:
        await db.execute(
            sa_delete(MatchingPaymentInvoice).where(
                MatchingPaymentInvoice.payment_detail_id.in_(affected_payment_ids),
                MatchingPaymentInvoice.match_status == "FAILED",
                MatchingPaymentInvoice.invoice_id.is_(None),
            )
        )

    await db.commit()


async def get_payment_by_id(payment_id: int, db: AsyncSession) -> PaymentDetail | None:
    result = await db.execute(select(PaymentDetail).where(PaymentDetail.id == payment_id))
    return result.scalar_one_or_none()


async def soft_delete_payment(payment_id: int, db: AsyncSession) -> None:
    result = await db.execute(select(PaymentDetail).where(PaymentDetail.id == payment_id))
    payment = result.scalar_one_or_none()
    if not payment:
        return
    payment.is_deleted = True  # type: ignore[assignment]
    await db.commit()


async def get_user_stats(db: AsyncSession) -> list[dict]:
    invoice_q = await db.execute(
        select(
            Document.user_id,
            sqlfunc.count(InvoiceData.id).label("invoices_uploaded"),
        )
        .join(InvoiceData, InvoiceData.document_id == Document.id)
        .where(
            Document.document_type == "INVOICE",
            Document.user_id.isnot(None),
            InvoiceData.is_deleted.is_(False),
        )
        .group_by(Document.user_id)
    )
    invoice_counts = {row.user_id: row.invoices_uploaded for row in invoice_q.all()}

    payment_q = await db.execute(
        select(
            Document.user_id,
            sqlfunc.count(PaymentDetail.id).label("payments_uploaded"),
        )
        .join(PaymentDetail, PaymentDetail.document_id == Document.id)
        .where(
            Document.document_type == "PAYMENT",
            Document.user_id.isnot(None),
            PaymentDetail.is_deleted.is_(False),
        )
        .group_by(Document.user_id)
    )
    payment_counts = {row.user_id: row.payments_uploaded for row in payment_q.all()}

    match_q = await db.execute(
        select(
            Document.user_id,
            sqlfunc.count(MatchingPaymentInvoice.id).label("matches_made"),
        )
        .join(PaymentDetail, PaymentDetail.document_id == Document.id)
        .join(MatchingPaymentInvoice, MatchingPaymentInvoice.payment_detail_id == PaymentDetail.id)
        .where(
            Document.document_type == "PAYMENT",
            Document.user_id.isnot(None),
            PaymentDetail.is_deleted.is_(False),
            MatchingPaymentInvoice.match_status.notin_(["FAILED"]),
        )
        .group_by(Document.user_id)
    )
    match_counts = {row.user_id: row.matches_made for row in match_q.all()}

    last_active_q = await db.execute(
        select(
            Document.user_id,
            sqlfunc.max(Document.uploaded_at).label("last_active"),
        )
        .where(Document.user_id.isnot(None))
        .group_by(Document.user_id)
    )
    last_active = {
        row.user_id: row.last_active.isoformat() if row.last_active else None
        for row in last_active_q.all()
    }

    all_user_ids = set(invoice_counts) | set(payment_counts) | set(match_counts) | set(last_active)

    return [
        {
            "user_id": uid,
            "invoices_uploaded": invoice_counts.get(uid, 0),
            "payments_uploaded": payment_counts.get(uid, 0),
            "matches_made": match_counts.get(uid, 0),
            "last_active": last_active.get(uid),
        }
        for uid in sorted(all_user_ids)
    ]