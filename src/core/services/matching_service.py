from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.matching_payment_invoice import MatchingPaymentInvoice
from src.data.repositories import matching_repository as repo


async def get_matches_by_payment(payment_id: int, db: AsyncSession) -> list[MatchingPaymentInvoice]:
    return await repo.get_matches_by_payment_id(payment_id, db)


async def get_matches_by_invoice(invoice_id: int, db: AsyncSession) -> list[MatchingPaymentInvoice]:
    return await repo.get_matches_by_invoice_id(invoice_id, db)


async def get_dashboard_summary(db: AsyncSession) -> dict:
    all_matches = await repo.get_all_matches(db)
    if not all_matches:
        return {"FULL": [], "PARTIAL": [], "OVERPAYMENT": [], "DUPLICATE": [], "FAILED": []}
    return {
        status: [m for m in all_matches if m.match_status == status]
        for status in ["FULL", "PARTIAL", "OVERPAYMENT", "DUPLICATE", "FAILED"]
    }


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
