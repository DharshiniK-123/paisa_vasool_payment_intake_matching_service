from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date, datetime

import pandas as pd
from fastapi import HTTPException, UploadFile
from rq import Queue
from sqlalchemy import insert as sa_insert, update as sa_update
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


def _row_to_text(row: dict) -> str:
    """
    Convert a single DataFrame row (as a dict) into a keyword-friendly text
    string so that classify_document_type can match against it.

    Column names keep their spaces (e.g. "invoice no", "amount paid") which
    aligns with both INVOICE_KEYWORDS and INVOICE_KEYWORDS_TABULAR in Llm_extractor.

    Example output:
        invoice no: INV-001 | invoice date: 2026-01-15 | amount: 5000 | currency: INR
    """
    pairs = [
        f"{col}: {val}"
        for col, val in row.items()
        if val is not None and str(val).strip() not in ("", "nan", "NaT")
    ]
    return " | ".join(pairs)


async def upload_document_and_enqueue(
    file: UploadFile,
    db: AsyncSession,
    job_id: str,
    user_id: int | None = None,
) -> dict:
    """
    Upload a file without requiring the caller to declare its type.
    The document is stored with document_type=UNKNOWN; the RQ worker
    will classify it via keyword search during extraction.
    """
    original_name = file.filename or ""
    extension = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""

    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '.{extension}'. Allowed: pdf, csv, xls, xlsx, jpg, jpeg, png, webp",
        )

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large. Maximum allowed size is 10MB.")
    await file.seek(0)

    storage_path, file_type, file_url, file_hash = await save_file(file, DocumentType.UNKNOWN)

    document_insert_stmt = (
        sa_insert(Document)
        .values(
            user_id=user_id,
            document_type=DocumentType.UNKNOWN,
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
) -> tuple[str, list[dict]]:
    """
    Download, classify, and extract records from the document.
    Returns (detected_document_type, list_of_records).
    The Document row's document_type is updated in-place after classification.
    """
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
                        detected_type, records = await _extract_multi_page(extracted)
                    else:
                        detected_type, records = await _extract_single(extracted)
                elif file_type in ("csv", "xlsx", "xls"):
                    # extracted is a pd.DataFrame returned by parse_text
                    detected_type, records = await _extract_dataframe(extracted)
                else:
                    raise HTTPException(status_code=400, detail=f"Unsupported file type: {file_type}")

                await db.execute(
                    sa_update(Document)
                    .where(Document.id == document_id)
                    .values(document_type=detected_type, status=DocumentStatus.EXTRACTED)
                )
                await db.commit()

                return detected_type, records

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

            # ── 1. Parse all date strings → date objects ───────────────────
            for date_field in DATE_FIELDS:
                if date_field in data:
                    data[date_field] = _parse_date(data[date_field])

            # ── 2. NULL GUARDS — prevent LLM nulls hitting non-nullable DB cols
            if document_type == DocumentType.INVOICE:
                if not data.get("invoice_number"):
                    data["invoice_number"] = "UNKNOWN"
                if not data.get("invoice_date"):
                    data["invoice_date"] = date.today()
                if not data.get("due_date"):
                    data["due_date"] = date.today()
                if data.get("total_amount") is None:
                    data["total_amount"] = 0.00

            elif document_type == DocumentType.PAYMENT:
                if not data.get("invoice_no"):
                    data["invoice_no"] = ""
                if data.get("payment_amount") is None:
                    data["payment_amount"] = 0.00
                if not data.get("paid_date"):
                    data["paid_date"] = date.today()

            # ── 3. Resolve customer ────────────────────────────────────────
            if data.get("customer_id"):
                customer_id = int(data["customer_id"])
            else:
                customer_id = await _resolve_customer(
                    name=data.get("customer_name"),
                    email=data.get("customer_email"),
                    db=db,
                    document_type=document_type,
                )

            # ── 4. Strip fields that don't belong in the DB model ──────────
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

            # ── 5. Insert ──────────────────────────────────────────────────
            model = InvoiceData if document_type == DocumentType.INVOICE else PaymentDetail

            document_save_stmt = (
                sa_insert(model)
                .values(document_id=document_id, customer_id=customer_id, **data)
                .returning(model.id)
            )
            result = await db.execute(document_save_stmt)
            await db.flush()
            inserted_id = result.scalar_one()

            # ── 6. Trigger matching ────────────────────────────────────────
            if document_type == DocumentType.PAYMENT:
                await run_matching_for_payment(inserted_id, db)

            elif document_type == DocumentType.INVOICE:
                invoice_number = data.get("invoice_number", "")
                if invoice_number and invoice_number != "UNKNOWN":
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


async def _extract_single(raw_content: str | dict) -> tuple[str, list[dict]]:
    detected_type, record = await run_extraction(raw_content)
    return detected_type, [record]


async def _extract_multi_page(pages: list[str]) -> tuple[str, list[dict]]:
    """
    Each page is classified independently. All pages must agree on type;
    a mismatch raises 422 rather than silently mixing records.
    """
    records: list[dict] = []
    detected_types: set[str] = set()

    for i, page_text in enumerate(pages):
        try:
            detected_type, record = await run_extraction(page_text)
            detected_types.add(detected_type)
            records.append(record)
        except HTTPException as e:
            if e.status_code == 422 and "could not be classified" in str(e.detail).lower():
                logger.warning("pdf_page_skipped_unclassifiable", extra={"page_index": i})
                continue
            logger.warning("pdf_page_extraction_skipped", extra={"page_index": i, "detail": e.detail})

    if not records:
        raise HTTPException(
            status_code=422,
            detail="No valid financial data could be extracted from any page of the PDF.",
        )

    if len(detected_types) > 1:
        raise HTTPException(
            status_code=422,
            detail=(
                f"PDF contains mixed document types ({', '.join(sorted(detected_types))}). "
                "Please upload a file that contains only invoices or only payments."
            ),
        )

    return detected_types.pop(), records


async def _extract_dataframe(df: pd.DataFrame) -> tuple[str, list[dict]]:
    """
    Extract records from a DataFrame returned by parse_text for CSV/Excel files.

    Each row is converted to a keyword-friendly text string via _row_to_text
    so that classify_document_type in Llm_extractor can match invoice/payment
    keywords against column names and values (e.g. "invoice no", "amount paid").

    The LLM then extracts structured fields from that same text.
    """
    if df.empty:
        raise HTTPException(
            status_code=422,
            detail="The uploaded spreadsheet appears to be empty.",
        )

    records: list[dict] = []
    detected_types: set[str] = set()

    for i, row in enumerate(df.to_dict(orient="records")):
        # Convert row → keyword-friendly text for classification + LLM extraction
        row_text = _row_to_text(row)

        if not row_text.strip():
            logger.debug("spreadsheet_row_skipped_empty", extra={"row_index": i})
            continue

        try:
            detected_type, result = await run_extraction(row_text)
            detected_types.add(detected_type)
            records.append(result)
        except HTTPException as e:
            if e.status_code == 422 and "could not be classified" in str(e.detail).lower():
                logger.warning("spreadsheet_row_skipped_unclassifiable", extra={"row_index": i})
                continue
            raise

    if not records:
        raise HTTPException(
            status_code=422,
            detail=(
                "No valid financial records could be extracted from the spreadsheet. "
                "Please ensure column headers include terms like 'invoice no', 'amount', "
                "'payment date', etc."
            ),
        )

    if len(detected_types) > 1:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Spreadsheet contains mixed document types ({', '.join(sorted(detected_types))}). "
                "Please upload a file that contains only invoices or only payments."
            ),
        )

    return detected_types.pop(), records


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