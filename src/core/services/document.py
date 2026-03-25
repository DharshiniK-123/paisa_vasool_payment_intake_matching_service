from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date, datetime

import pandas as pd
from fastapi import HTTPException, UploadFile
from rq import Queue
from sqlalchemy import delete as sa_delete
from sqlalchemy import insert as sa_insert
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.control.extraction.Llm_extractor import run_extraction
from src.core.services.extraction_service import extract_text
from src.core.services.matching import run_matching_for_payment
from src.core.services.storage_service import save_file
from src.core.tasks.document_task import process_document_task, process_document_task_sync
from src.data.clients.redis_clients import get_async_redis_client, redis_connection
from src.data.models.postgres.customer import Customer
from src.data.models.postgres.document import Document
from src.data.models.postgres.invoice_data import InvoiceData
from src.data.models.postgres.matching_payment_invoice import MatchingPaymentInvoice
from src.data.models.postgres.payment_detail import PaymentDetail
from src.data.repositories.generic_repository import (
    get_instance_by_any,
    update_instance_by_id,
)
from src.utils.normalize import _normalize
from src.utils.worker_trigger import trigger_worker

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {"pdf", "csv", "xlsx", "xls", "jpg", "jpeg", "png", "gif", "webp"}
IMAGE_TYPES = {"jpg", "jpeg", "png", "gif", "webp"}

DATE_FIELDS = ("invoice_date", "due_date", "payment_date", "transaction_date", "paid_date")


def _make_session():
    engine = create_async_engine(str(os.getenv("DATABASE_URL")))
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, autoflush=False)
    return engine, factory()


def _parse_date(val) -> date | None:
    if val is None:
        return None
    if isinstance(val, date):
        return val
    try:
        return datetime.strptime(str(val).strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


async def upload_document_and_enqueue(
    file: UploadFile,
    document_type: str,
    db: AsyncSession,
    job_id: str,
    user_id: int | None = None,
) -> dict:
    original_name = file.filename or ""
    extension = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"""Unsupported file type '.{extension}'. 
            Allowed: pdf, csv, xlsx, jpg, png, webp""",
        )

    storage_path, file_type, file_url = await save_file(file, document_type)

    stmt = (
        sa_insert(Document)
        .values(
            user_id=user_id,
            document_type=document_type,
            file_name=original_name,
            file_type=file_type,
            storage_path=storage_path,
            status="PENDING",
        )
        .returning(Document.id)
    )

    result = await db.execute(stmt)
    await db.commit()
    document_id = result.scalar_one()

    kwargs = {
        "document_id": document_id,
        "storage_path": storage_path,
        "file_type": file_type,
        "file_url": file_url,
        "document_type": document_type,
        "job_id": job_id,
    }

    try:
        if redis_connection is not None:
            q = Queue(connection=redis_connection)
            print(q)
            print("before calling process_document_task_sync")
            await asyncio.to_thread(
                q.enqueue,
                process_document_task_sync,
                kwargs=kwargs,
                job_timeout=900,
                result_ttl=3600,
            )

            asyncio.create_task(trigger_worker())

        else:
            await process_document_task(**kwargs)

    except Exception:
        await process_document_task(**kwargs)

    return {"document_id": document_id}


async def extract_document_data(
    document_id: int,
    storage_path: str,
    file_type: str,
    file_url: str,
    document_type: str,
) -> list[dict]:
    engine, db = _make_session()

    try:
        async with db:
            await update_instance_by_id(document_id, Document, db, status="PROCESSING")

            try:
                extracted = await extract_text(storage_path, file_type, file_url)
            except HTTPException:
                await update_instance_by_id(document_id, Document, db, status="FAILED")
                raise

            try:
                if file_type == "pdf" or file_type in IMAGE_TYPES:
                    records = await _extract_single(extracted, document_type)
                elif file_type in ("csv", "xlsx", "xls"):
                    records = await _extract_dataframe(extracted, document_type)
                else:
                    raise HTTPException(
                        status_code=400, detail=f"Unsupported file type: {file_type}"
                    )

                await update_instance_by_id(document_id, Document, db, status="EXTRACTED")
                return records

            except HTTPException:
                await update_instance_by_id(document_id, Document, db, status="FAILED")
                raise
            except Exception as e:
                await update_instance_by_id(document_id, Document, db, status="FAILED")
                raise HTTPException(status_code=500, detail="Extraction failed") from e
    finally:
        await engine.dispose()


async def save_document_records(
    document_id: int,
    document_type: str,
    records: list[dict],
) -> int:
    engine, db = _make_session()

    try:
        async with db:
            count = 0

            for data in records:
                data = dict(data)

                for date_field in DATE_FIELDS:
                    if date_field in data:
                        data[date_field] = _parse_date(data[date_field])

                if data.get("customer_id"):
                    customer_id = int(data["customer_id"])
                else:
                    customer_id = await _resolve_customer(
                        name=data.get("customer_name"),
                        email=data.get("customer_email"),
                        db=db,
                        document_type=document_type,
                    )

                for field in (
                    "id",
                    "document_id",
                    "customer_id",
                    "_sa_instance_state",
                    "customer_name",
                    "customer_email",
                    "customer_phone",
                    "payer_name",
                    "payer_email",
                    "payer_phone",
                ):
                    data.pop(field, None)

                model = InvoiceData if document_type == "INVOICE" else PaymentDetail

                stmt = (
                    sa_insert(model)
                    .values(document_id=document_id, customer_id=customer_id, **data)
                    .returning(model.id)
                )
                result = await db.execute(stmt)
                await db.commit()
                inserted_id = result.scalar_one()

                if document_type == "PAYMENT":
                    await run_matching_for_payment(inserted_id, db)

                elif document_type == "INVOICE":
                    invoice_number = data.get("invoice_number", "")
                    if invoice_number:
                        await _rematch_pending_payments_for_invoice(
                            invoice_number=invoice_number,
                            customer_id=customer_id,
                            db=db,
                        )

                count += 1

            await update_instance_by_id(document_id, Document, db, status="PARSED")

            try:
                redis = get_async_redis_client()
                await redis.delete(f"preview:{document_id}")
                await redis.aclose()
            except Exception as e:
                logger.warning("redis_preview_delete_failed", extra={"error": str(e)})

            return count
    finally:
        await engine.dispose()


async def _rematch_pending_payments_for_invoice(
    invoice_number: str,
    customer_id: int,
    db: AsyncSession,
) -> None:
    """
    Called after a new invoice is saved.
    Finds every non-deleted payment for the same customer whose invoice_no
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
                MatchingPaymentInvoice.match_status.in_(["FULL", "PARTIAL", "OVERPAYMENT"]),
            )
        )
        if existing.scalars().first() is not None:
            continue
        await db.execute(
            sa_delete(MatchingPaymentInvoice).where(
                MatchingPaymentInvoice.payment_detail_id == payment.id,
                MatchingPaymentInvoice.match_status == "FAILED",
            )
        )
        await db.flush()

        logger.info(
            "rematch_pending_payment",
            extra={"payment_id": payment.id, "invoice_number": invoice_number},
        )
        await run_matching_for_payment(int(payment.id), db)


async def _extract_single(raw_text: str, document_type: str) -> list[dict]:
    records = await run_extraction(raw_text, document_type)
    return [records]


async def _extract_dataframe(df: pd.DataFrame, document_type: str) -> list[dict]:
    records = []
    for row in df.to_dict(orient="records"):
        text = json.dumps(row, default=str)
        result = await run_extraction(text, document_type)
        records.append(result)
    return records


async def _resolve_customer(
    name: str | None,
    email: str | None,
    db: AsyncSession,
    document_type: str = "INVOICE",
) -> int:
    clean_email = (email or "").strip().lower()
    if clean_email in ("", "null", "none"):
        if document_type == "INVOICE":
            raise HTTPException(
                status_code=422,
                detail=(
                    "Customer email not found in document. "
                    "Email is required for reminders. "
                    "Add the customer manually first."
                ),
            )
        raise HTTPException(
            status_code=422,
            detail=(
                "Customer email is missing from the payment record. "
                "Cannot resolve the customer without an email address."
            ),
        )

    existing = await get_instance_by_any(Customer, db, {"email": email})
    if existing:
        return int(existing.id)

    if document_type == "INVOICE":
        from src.data.repositories.generic_repository import insert_instance

        await insert_instance(
            Customer,
            db,
            name=name or (email or "").split("@")[0],
            email=email,
        )
        created = await get_instance_by_any(Customer, db, {"email": email})
        return int(created.id)

    raise HTTPException(
        status_code=422,
        detail=(
            f"Customer with email '{email}' does not exist. "
            "Payments can only be applied to existing customers."
        ),
    )