from __future__ import annotations

import logging
from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.enums import DocumentType
from src.data.repositories import document_repository as repo

logger = logging.getLogger(__name__)

INVOICE_REQUIRED_FIELDS = [
    "customer_id",
    "invoice_number",
    "invoice_date",
    "due_date",
    "total_amount"]

PAYMENT_REQUIRED_FIELDS = [
    "customer_id",
    "payment_amount",
    "paid_date"]


def _is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


def validate_records(records: list, document_type: str) -> None:
    """Validate that all required fields are present in each record."""
    required = INVOICE_REQUIRED_FIELDS if document_type == DocumentType.INVOICE else PAYMENT_REQUIRED_FIELDS
    errors = []
    for idx, record in enumerate(records, start=1):
        missing = [f for f in required if _is_empty(record.get(f))]
        if missing:
            errors.append(f"Record {idx}: missing — {', '.join(missing)}")
    if errors:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Validation failed. Some records have missing required fields.",
                "errors": errors,
            },
        )


async def resolve_customer_ids(
    records: list[dict], document_type: str, document_id: int, db: AsyncSession
) -> None:
    """
    For each record without a customer_id, look up or create the customer.
    Mutates records in-place by setting customer_id.
    Flushes new customers to db but does NOT commit (caller commits after validation).
    """
    for idx, record in enumerate(records, start=1):
        if record.get("customer_id"):
            continue

        customer_name = (record.get("customer_name") or "").strip()
        customer_email = (record.get("customer_email") or "").strip()

        if not customer_name and not customer_email:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Validation failed. Some records have missing required fields.",
                    "errors": [
                        f"Record {idx}: missing — customer_id "
                        "(and no customer_name or customer_email to look up)"
                    ],
                },
            )

        customer = None
        if customer_email:
            customer = await repo.get_customer_by_email(customer_email, db)
        if not customer and customer_name:
            customer = await repo.get_customer_by_name(customer_name, db)

        if not customer:
            if document_type == DocumentType.PAYMENT:
                identifier = customer_email or customer_name
                raise HTTPException(
                    status_code=422,
                    detail={
                        "message": "Validation failed. Customer not found.",
                        "errors": [
                            f"Record {idx}: customer '{identifier}' does not exist. "
                            "Payments can only be applied to existing customers."
                        ],
                    },
                )
            else:
                if not customer_email:
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "message": "Validation failed. Cannot create customer.",
                            "errors": [
                                f"Record {idx}: no email provided — "
                                f"cannot auto-create customer '{customer_name}'."
                            ],
                        },
                    )
                customer = await repo.create_customer(
                    db,
                    name=customer_name or customer_email,
                    email=customer_email,
                    phone=record.get("customer_phone") or None,
                )

        record["customer_id"] = customer.id


async def check_duplicates(
    records: list[dict], document_type: str, document_id: int, db: AsyncSession
) -> None:
    """Raise HTTPException if any duplicate invoice number or payment reference is found."""
    for _idx, record in enumerate(records, start=1):
        if document_type == DocumentType.PAYMENT:
            invoice_no = record.get("invoice_no")
            payment_reference = record.get("payment_reference")
            if invoice_no and payment_reference:
                existing = await repo.find_duplicate_payment_reference(
                    payment_reference, document_id, db
                )
                if existing:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"Duplicate payment detected for invoice {invoice_no} "
                            f"with reference {payment_reference}."
                        ),
                    )

        if document_type == DocumentType.INVOICE:
            invoice_number = record.get("invoice_number")
            if invoice_number:
                existing = await repo.find_duplicate_invoice_number(
                    invoice_number, document_id, db
                )
                if existing:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Invoice {invoice_number} already exists.",
                    )


def build_invoices_response(rows: list) -> list[dict]:
    """Build the grouped invoice+matches response from raw DB rows."""
    invoice_map: dict = {}
    matches_map: defaultdict = defaultdict(list)

    for row in rows:
        inv = row.InvoiceData
        inv_id = inv.id
        if inv_id not in invoice_map:
            invoice_map[inv_id] = {
                **{k: v for k, v in inv.__dict__.items() if not k.startswith("_")},
                "customer_name": row.customer_name,
                "customer_email": row.customer_email,
            }
        if row.match_id is not None:
            matches_map[inv_id].append({
                "match_id": row.match_id,
                "match_status": row.match_status,
                "matched_amount": row.matched_amount,
                "amount_pending": row.amount_pending,
                "match_reason": row.match_reason,
                "payment_detail_id": row.payment_detail_id,
                "matched_at": row.matched_at,
            })

    return [
        {**inv_data, "matches": matches_map.get(inv_id, [])}
        for inv_id, inv_data in invoice_map.items()
    ]
