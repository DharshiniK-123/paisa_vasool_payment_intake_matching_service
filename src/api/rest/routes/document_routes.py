import json
import uuid
from typing import Literal, List

from fastapi import APIRouter, HTTPException, UploadFile, File, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.customer import Customer
from src.api.rest.dependencies import get_db, get_current_user
from src.core.services.document import upload_document_and_enqueue, save_document_records
from src.data.models.postgres.document import Document
from src.data.models.postgres.invoice_data import InvoiceData
from src.data.models.postgres.payment_detail import PaymentDetail
from src.data.repositories.generic_repository import get_instance_by_id, bulk_get_instance
from src.data.clients.redis_clients import redis_client

router = APIRouter(prefix="/documents", tags=["Documents"])

MAX_FILE_SIZE = 10 * 1024 * 1024


@router.post("/upload")
async def upload_document(document_type: Literal["INVOICE", "PAYMENT"] = Query(...),file: UploadFile = File(...),db: AsyncSession = Depends(get_db),user: dict = Depends(get_current_user),):
    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large. Maximum allowed size is 10MB.")
    await file.seek(0)
    try:
        job_id = str(uuid.uuid4())
        result = await upload_document_and_enqueue(
            file=file, document_type=document_type, db=db, job_id=job_id,
        )
        return {
            "file_name":   file.filename,
            "status":      "PROCESSING",
            "job_id":      job_id,
            "document_id": result["document_id"],
            "message":     "File uploaded. Extraction running in background.",
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail="File Upload unsuccessfull")


@router.get("/jobs/{job_id}/status")
async def get_job_status(job_id: str,user: dict = Depends(get_current_user),):
    try:
        data = redis_client.get(f"job:{job_id}")
        if not data:
            return {
                "job_id":  job_id,
                "status":  "PROCESSING",
                "message": "Document is being processed. Please check back shortly.",
            }
        return {"job_id": job_id, **json.loads(data)}
    except Exception:
        raise HTTPException(status_code=500, detail="Could not fetch job status.")


class SaveRecordsRequest(BaseModel):
    document_type: Literal["INVOICE", "PAYMENT"]
    records: List[dict]


@router.post("/{document_id}/save")
async def save_records(document_id: int,body: SaveRecordsRequest,db: AsyncSession = Depends(get_db),user: dict = Depends(get_current_user),):
    try:
        doc = await get_instance_by_id(document_id, Document, db)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found.")
        if not body.records:
            raise HTTPException(status_code=400, detail="No records provided to save.")
        count = await save_document_records(
            document_id=document_id,
            document_type=body.document_type,
            records=body.records,
            db=db,
        )
        return {
            "document_id":   document_id,
            "status":        "PARSED",
            "records_saved": count,
            "message":       "Records saved successfully.",
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail="Could not save the document")
    
@router.get("/")
async def list_documents(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await bulk_get_instance(Document, db)
    except Exception:
        raise HTTPException(status_code=500, detail="Could not fetch documents.")


@router.get("/{document_id}")
async def get_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        doc = await get_instance_by_id(document_id, Document, db)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found.")
        return doc
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Could not fetch document.")


@router.get("/{document_id}/invoices")
async def get_document_invoices(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        result = await db.execute(
            select(InvoiceData, Customer.name.label("customer_name"), Customer.email.label("customer_email"))
            .join(Customer, InvoiceData.customer_id == Customer.id, isouter=True)
            .where(InvoiceData.document_id == document_id)
        )
        rows = result.all()
        if not rows:
            raise HTTPException(status_code=404, detail=f"No invoices found for document {document_id}.")
        return [{**row.InvoiceData.__dict__, "customer_name": row.customer_name, "customer_email": row.customer_email} for row in rows]
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Could not fetch invoices.")


@router.get("/{document_id}/payments")
async def get_document_payments(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        result = await db.execute(
            select(
                PaymentDetail.id, PaymentDetail.document_id, PaymentDetail.customer_id,
                PaymentDetail.invoice_no, PaymentDetail.payment_amount.label("amount"),
                PaymentDetail.currency, PaymentDetail.paid_date.label("payment_date"),
                PaymentDetail.payment_reference.label("reference_number"),
                Customer.name.label("payer_name"), Customer.email.label("payer_email"),
                Customer.phone.label("payer_phone"),
            )
            .join(Customer, PaymentDetail.customer_id == Customer.id, isouter=True)
            .where(PaymentDetail.document_id == document_id)
        )
        rows = result.mappings().all()
        if not rows:
            raise HTTPException(status_code=404, detail=f"No payments found for document {document_id}.")
        return [dict(row) for row in rows]
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Could not fetch payments.")