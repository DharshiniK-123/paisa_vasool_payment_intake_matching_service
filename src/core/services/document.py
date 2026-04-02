from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date, datetime

import pandas as pd
from fastapi import HTTPException, UploadFile
from rq import Queue
from sqlalchemy import insert as sa_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from src.core.services.matching.matching_service import _rematch_payments_for_invoice
from src.control.extraction.Llm_extractor import run_extraction
from src.core.enums import DocumentStatus, DocumentType, MatchStatus
from src.core.services.extraction_service import parse_text
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
from src.utils.worker_trigger import trigger_worker

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {"pdf", "csv", "xlsx", "xls", "jpg", "jpeg", "png", "webp"}
IMAGE_TYPES = {"jpg", "jpeg", "png", "webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024
DATE_FIELDS = ("invoice_date", "due_date", "payment_date", "transaction_date", "paid_date")
PREVIEW_KEY_PREFIX = "preview:"


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
            Allowed: pdf, csv, xls, xlsx, jpg, jpeg, png, webp""",
        )
    
    contents = await file.read()

    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413, 
            detail="File too large. Maximum allowed size is 10MB."
        )
    await file.seek(0)

    storage_path, file_type, file_url, file_hash = await save_file(file, document_type)

    document_insert_stmt = (
        sa_insert(Document)
        .values(
            user_id=user_id,
            document_type=document_type,
            file_name=original_name,
            file_type=file_type,
            storage_path=storage_path,
            status=DocumentStatus.PENDING,
        )
        .returning(Document.id)
    )

    result = await db.execute(document_insert_stmt)
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
            await update_instance_by_id(document_id, Document, db, status=DocumentStatus.PROCESSING)

            try:
                extracted = await parse_text(storage_path, file_type, file_url)
            except HTTPException:
                await update_instance_by_id(document_id, Document, db, status=DocumentStatus.FAILED)
                raise

            try:
                if file_type == "pdf" or file_type in IMAGE_TYPES:
                    if file_type == "pdf":
                        records = await _extract_multi_page(extracted, document_type)
                    else:
                        records = await _extract_single(extracted, document_type)
                elif file_type in ("csv", "xlsx", "xls"):
                    records = await _extract_dataframe(extracted, document_type)
                else:
                    raise HTTPException(
                        status_code=400, detail=f"Unsupported file type: {file_type}"
                    )

                await update_instance_by_id(document_id, Document, db, status=DocumentStatus.EXTRACTED)
                return records

            except HTTPException:
                await update_instance_by_id(document_id, Document, db, status=DocumentStatus.FAILED)
                raise
            except Exception as e:
                await update_instance_by_id(document_id, Document, db, status=DocumentStatus.FAILED)
                raise HTTPException(status_code=500, detail="Extraction failed") from e
    finally:
        await engine.dispose()


async def save_document_records(
    document_id: int,
    document_type: str,
    records: list[dict],
    db: AsyncSession | None = None,
) -> int:
    engine = None
    should_close = False

    if db is None:
        engine, db = _make_session()
        should_close = True

    async def _run(db: AsyncSession) -> int:
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

            model = InvoiceData if document_type == DocumentType.INVOICE else PaymentDetail

            document_save_stmt = (
                sa_insert(model)
                .values(document_id=document_id, customer_id=customer_id, **data)
                .returning(model.id)
            )
            result = await db.execute(document_save_stmt)
            await db.flush()
            inserted_id = result.scalar_one()

            if document_type == DocumentType.PAYMENT:
                await run_matching_for_payment(inserted_id, db)

            elif document_type == DocumentType.INVOICE:
                invoice_number = data.get("invoice_number", "")
                if invoice_number:
                    await _rematch_payments_for_invoice(
                        invoice_number=invoice_number,
                        customer_id=customer_id,
                        db=db,
                    )

            count += 1
        await db.commit()

        await update_instance_by_id(document_id, Document, db, status=DocumentStatus.PARSED)

        try:
            redis = get_async_redis_client()
            await redis.delete(f"{PREVIEW_KEY_PREFIX}{document_id}")
            await redis.aclose()
        except Exception as e:
            logger.warning("redis_preview_delete_failed", extra={"error": str(e)})

        return count

    try:
        if should_close:
            async with db:
                return await _run(db)
        else:
            return await _run(db)
    finally:
        if should_close and engine:
            await engine.dispose()



async def _extract_single(raw_text: str, document_type: str) -> list[dict]:
    records = await run_extraction(raw_text, document_type)
    return [records]


async def _extract_multi_page(pages: list[str], document_type: str) -> list[dict]:
    records = []
    for i, page_text in enumerate(pages):
        try:
            record = await run_extraction(page_text, document_type)
            records.append(record)
        except HTTPException as e:
            if e.status_code == 422 and (
                "mismatch" in str(e.detail).lower() or
                "does not appear" in str(e.detail).lower()
            ):
                raise
            logger.warning(
                "pdf_page_extraction_skipped",
                extra={"page_index": i, "detail": e.detail},
            )
    if not records:
        raise HTTPException(
            status_code=422,
            detail="No valid invoice data could be extracted from any page of the PDF.",
        )
    return records


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
    document_type: str = DocumentType.INVOICE,
) -> int:
    clean_email = (email or "").strip().lower()
    if clean_email in ("", "null", "none"):
        if document_type == DocumentType.INVOICE:
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

    if document_type == DocumentType.INVOICE:
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
