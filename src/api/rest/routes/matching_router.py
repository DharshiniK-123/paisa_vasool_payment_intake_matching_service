import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select,or_
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.customer import Customer
from src.api.rest.dependencies import get_current_user, get_db
from src.data.models.postgres.matching_payment_invoice import MatchingPaymentInvoice
from src.data.models.postgres.payment_detail import PaymentDetail
from src.data.models.postgres.invoice_data import InvoiceData
from src.schemas.payment_intake_matching import MatchingResponse

router = APIRouter(prefix="/matching", tags=["Matching"])

ACTIVE_PAYMENT = PaymentDetail.is_deleted.is_(False)
ACTIVE_INVOICE = InvoiceData.is_deleted.is_(False)


@router.get("/payment/{payment_id}", response_model=list[MatchingResponse])
async def get_matches_by_payment(payment_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)):
    try:
        result = await db.execute(
            select(MatchingPaymentInvoice)
            .where(MatchingPaymentInvoice.payment_detail_id == payment_id)
            .order_by(MatchingPaymentInvoice.created_at.desc())
        )
        matches = result.scalars().all()

        if not matches:
            raise HTTPException(status_code=404, detail=f"No matches found for payment {payment_id}.")

        return matches

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Could not fetch payment matches.")


@router.get("/invoice/{invoice_id}", response_model=list[MatchingResponse])
async def get_matches_by_invoice(invoice_id: int, db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)):
    try:
        result = await db.execute(
            select(MatchingPaymentInvoice)
            .where(MatchingPaymentInvoice.invoice_id == invoice_id)
            .order_by(MatchingPaymentInvoice.created_at.desc())
        )

        matches = result.scalars().all()

        if not matches:
            raise HTTPException(status_code=404, detail=f"No matches found for invoice {invoice_id}.")

        return matches

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Could not fetch invoice matches.")


@router.get("/dashboard/summary")
async def get_dashboard_summary(db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)):
    try:
        result = await db.execute(
            select(MatchingPaymentInvoice).order_by(MatchingPaymentInvoice.created_at.desc())
        )

        all_matches = result.scalars().all()

        if not all_matches:
            return {"FULL": [], "PARTIAL": [], "OVERPAYMENT": [], "DUPLICATE": [], "FAILED": []}

        return {
            status: [m for m in all_matches if m.match_status == status]
            for status in ["FULL", "PARTIAL", "OVERPAYMENT", "DUPLICATE", "FAILED"]
        }

    except Exception:
        raise HTTPException(status_code=500, detail="Could not load dashboard summary.")


@router.get("/dashboard/unmatched-payments")
async def get_unmatched_payments(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    try:
        matched_ids = select(MatchingPaymentInvoice.payment_detail_id).where(
            MatchingPaymentInvoice.match_status.in_(["FULL", "PARTIAL", "OVERPAYMENT"])
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
            .where(
                PaymentDetail.id.notin_(matched_ids),
                ACTIVE_PAYMENT
            )
        )

        rows = result.mappings().all()
        return [dict(row) for row in rows]

    except Exception:
        raise HTTPException(status_code=500, detail="Could not fetch unmatched payments.")


@router.get("/dashboard/unmatched-invoices")
async def get_unmatched_invoices(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    try:
        result = await db.execute(
            select(
                InvoiceData,
                Customer.name.label("customer_name"),
                Customer.email.label("customer_email"),
            )
            .join(Customer, InvoiceData.customer_id == Customer.id, isouter=True)
            .where(
                InvoiceData.payment_status == "UNPAID",
                ACTIVE_INVOICE
            )
        )

        rows = result.all()

        return [
            {
                **{k: v for k, v in row.InvoiceData.__dict__.items() if not k.startswith("_")},
                "customer_name": row.customer_name,
                "customer_email": row.customer_email,
            }
            for row in rows
        ]

    except Exception:
        raise HTTPException(status_code=500, detail="Could not fetch unmatched invoices.")


@router.get("/invoice-detail/{invoice_id}")
async def get_invoice_detail(invoice_id: int, db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(
            select(
                InvoiceData,
                Customer.name.label("customer_name"),
                Customer.email.label("customer_email"),
            )
            .join(Customer, InvoiceData.customer_id == Customer.id, isouter=True)
            .where(
                InvoiceData.id == invoice_id,
                ACTIVE_INVOICE
            )
        )

        row = result.first()

        if not row:
            raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found.")

        data = {k: v for k, v in row.InvoiceData.__dict__.items() if not k.startswith("_")}
        data["customer_name"] = row.customer_name
        data["customer_email"] = row.customer_email

        return data

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not fetch invoice detail: {str(e)}")


@router.get("/payment-detail/{payment_id}")
async def get_payment_detail(payment_id: int, db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(
            select(
                PaymentDetail,
                Customer.name.label("payer_name"),
                Customer.email.label("payer_email"),
            )
            .join(Customer, PaymentDetail.customer_id == Customer.id, isouter=True)
            .where(
                PaymentDetail.id == payment_id,
                ACTIVE_PAYMENT
            )
        )

        row = result.first()

        if not row:
            raise HTTPException(status_code=404, detail=f"Payment {payment_id} not found.")

        data = {k: v for k, v in row.PaymentDetail.__dict__.items() if not k.startswith("_")}

        data["payer_name"] = row.payer_name
        data["payer_email"] = row.payer_email
        data["amount"] = data.pop("payment_amount", None)
        data["payment_date"] = data.pop("paid_date", None)
        data["reference_number"] = data.pop("payment_reference", None)

        return data

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not fetch payment detail: {str(e)}")

@router.get("/dashboard/recent")
async def get_recent_matches(limit: int = 20, db: AsyncSession = Depends(get_db), user: dict = Depends(get_current_user)):
    try:
        if limit <= 0 or limit > 100:
            raise HTTPException(status_code=400, detail="Limit must be between 1 and 100.")

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

        return result.scalars().all()

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Could not fetch recent matches.")

@router.get("/dashboard/discrepancies")
async def get_discrepancies(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        result = await db.execute(
            select(
                MatchingPaymentInvoice.id,
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
                MatchingPaymentInvoice.match_status.in_(["FAILED", "DUPLICATE","PARTIAL","OVERPAYMENT"]),
                ACTIVE_PAYMENT
            )
            .order_by(MatchingPaymentInvoice.created_at.desc())
        )

        rows = result.mappings().all()
        return [dict(row) for row in rows]

    except Exception:
        raise HTTPException(status_code=500, detail="Could not fetch discrepancies.")