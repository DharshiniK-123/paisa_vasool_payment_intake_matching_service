import pandas as pd
from fastapi import UploadFile, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from src.data.models.postgres.document import Document
from src.data.models.postgres.invoice_data import InvoiceData
from src.data.models.postgres.payment_detail import PaymentDetail
from src.data.models.postgres.customer import Customer
from src.data.repositories.generic_repository import (insert_instance,get_instance_by_any,update_instance_by_id,)
from src.core.services.storage_service import save_file_locally
from src.core.services.extraction_service import extract_text
from src.control.extraction.Llm_extractor import run_extraction, run_extraction_batch
from src.core.services.matching_service import run_matching_for_payment
from src.data.clients.postgres_client import AsyncSessionLocal
from rq import Queue
from src.data.clients.redis_clients import redis_connection
from src.core.tasks.document_task import process_document_task

ALLOWED_EXTENSIONS = {"pdf", "csv", "xlsx", "xls", "jpg", "jpeg", "png", "gif", "webp"}
IMAGE_TYPES        = {"jpg", "jpeg", "png", "gif", "webp"}



async def upload_document_and_enqueue(file: UploadFile,document_type: str,db: AsyncSession,job_id: str,) -> dict:
    original_name = file.filename or ""
    extension = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '.{extension}'. Allowed: pdf, csv, xlsx, jpg, png, webp",
        )
    storage_path, file_type, file_url = await save_file_locally(file, document_type)
    await insert_instance(
        Document, db,
        document_type=document_type,
        file_name=original_name,
        file_type=file_type,
        storage_path=storage_path,
        status="PENDING",
    )
    document = await get_instance_by_any(Document, db, {"storage_path": storage_path})
    document_id = document.id

    q = Queue(connection=redis_connection)
    q.enqueue(
        process_document_task,
        kwargs={
            "document_id":   document_id,
            "storage_path":  storage_path,
            "file_type":     file_type,
            "file_url":      file_url,
            "document_type": document_type,
            "job_id":        job_id,
        },
        job_timeout=300,
        result_ttl=3600,
    )
    return {"document_id": document_id}



async def extract_document_data(document_id: int,storage_path: str,file_type: str,file_url: str,document_type: str,) -> list[dict]:

    async with AsyncSessionLocal() as db:
        await update_instance_by_id(document_id, Document, db, status="PROCESSING")
        try:
            extracted = extract_text(storage_path, file_type, file_url)
        except HTTPException:
            await update_instance_by_id(document_id, Document, db, status="FAILED")
            raise

        try:
            if file_type == "pdf" or file_type in IMAGE_TYPES:
                records = await _extract_single(extracted, document_type)
            elif file_type in ("csv", "xlsx", "xls"):
                records = await _extract_dataframe(extracted, document_type)
            else:
                raise HTTPException(status_code=400, detail=f"Unsupported file type: {file_type}")

            await update_instance_by_id(document_id, Document, db, status="EXTRACTED")
            return records

        except HTTPException:
            await update_instance_by_id(document_id, Document, db, status="FAILED")
            raise
        except Exception as e:
            await update_instance_by_id(document_id, Document, db, status="FAILED")
            raise HTTPException(status_code=500, detail="Extraction failed")



async def save_document_records( document_id: int, document_type: str, records: list[dict], db: AsyncSession,) -> int:
    count = 0
    for data in records:
        data = dict(data)
        customer_id = await _resolve_customer(
            name=data.pop("customer_name", None),
            email=data.pop("customer_email", None),
            db=db,
        )
        for field in ("id", "document_id", "customer_id", "_sa_instance_state",
                      "customer_phone", "payer_name", "payer_email", "payer_phone"):
            data.pop(field, None)
        model = InvoiceData if document_type == "INVOICE" else PaymentDetail
        await insert_instance(model, db, document_id=document_id, customer_id=customer_id, **data)
        if document_type == "PAYMENT":
            payment = await get_instance_by_any(PaymentDetail, db, {"document_id": document_id})
            await run_matching_for_payment(payment.id, db)
        count += 1
    await update_instance_by_id(document_id, Document, db, status="PARSED")
    from src.data.clients.redis_clients import redis_client
    redis_client.delete(f"preview:{document_id}")
    return count


async def _extract_single(raw_text: str, document_type: str) -> list[dict]:
    data = await run_extraction(raw_text, document_type)
    return [data]


async def _extract_dataframe(df: pd.DataFrame, document_type: str) -> list[dict]:
    df_text = df.to_string(index=False)
    return await run_extraction_batch(df_text, document_type)


async def _resolve_customer(
    name: str | None,
    email: str | None,
    db: AsyncSession,
) -> int:
    if not email or str(email).lower() == "null":
        raise HTTPException(
            status_code=422,
            detail=(
                "Customer email not found in document. "
                "Email is required for reminders. "
                "Add the customer manually first."
            ),
        )
    existing = await get_instance_by_any(Customer, db, {"email": email})
    if existing:
        return existing.id
    await insert_instance(Customer, db, name=name or email.split("@")[0], email=email)
    created = await get_instance_by_any(Customer, db, {"email": email})
    return created.id