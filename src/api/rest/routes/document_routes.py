from __future__ import annotations

import json
import logging
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rest.dependencies import get_current_user, get_db
from src.core.services import document_service as service
from src.core.services.document import save_document_records, upload_document_and_enqueue
from src.data.clients.redis_clients import get_async_redis_client
from src.data.repositories import document_repository as repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["Documents"])

MAX_FILE_SIZE = 10 * 1024 * 1024


@router.post("/upload")
async def upload_document(
    document_type: Literal["INVOICE", "PAYMENT"] = Query(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Upload document(Invoice/Payment) to the GCS bucket and
    parse the text and extract the structured output"""
    import uuid

    try:
        contents = await file.read()
        if len(contents) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=413, detail="File too large. Maximum allowed size is 10MB."
            )
        await file.seek(0)

        job_id = str(uuid.uuid4())
        result = await upload_document_and_enqueue(
            file=file,
            document_type=document_type,
            db=db,
            job_id=job_id,
            user_id=user.get("id"),
        )
        return {
            "file_name": file.filename,
            "status": "PROCESSING",
            "job_id": job_id,
            "document_id": result["document_id"],
            "message": "File uploaded. Extraction running in background.",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="File upload unsuccessful.") from e


@router.get("/jobs/{job_id}/status")
async def get_job_status(job_id: str, user: dict = Depends(get_current_user)):
    """Status of the rq worker"""
    try:
        redis_client = get_async_redis_client()
        data = await redis_client.get(f"job:{job_id}") if redis_client else None
        if not data:
            return {
                "job_id": job_id,
                "status": "PROCESSING",
                "message": "Document is being processed. Please check back shortly.",
            }
        return {"job_id": job_id, **json.loads(data)}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Could not fetch job status.") from e


@router.get("/stats")
async def get_user_stats(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Fetch statistics for the admin dashboard"""
    try:
        return await repo.get_user_stats(db)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not fetch user stats: {str(e)}") from e


class SaveRecordsRequest(BaseModel):
    document_type: Literal["INVOICE", "PAYMENT"]
    records: list[dict]


@router.post("/{document_id}/save")
async def save_records(
    document_id: int,
    body: SaveRecordsRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Save records and match them"""
    try:
        doc = await repo.get_document_by_id(document_id, db)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found.")
        if not body.records:
            raise HTTPException(status_code=400, detail="No records provided.")

        await service.resolve_customer_ids(body.records, body.document_type, document_id, db)
        await db.commit()

        service.validate_records(body.records, body.document_type)
        await service.check_duplicates(body.records, body.document_type, document_id, db)

        count = await save_document_records(
            document_id=document_id,
            document_type=body.document_type,
            records=body.records,
        )
        return {
            "document_id": document_id,
            "status": "PARSED",
            "records_saved": count,
            "message": "Records saved successfully.",
        }
    except HTTPException:
        raise
    except IntegrityError as e:
        raise HTTPException(
            status_code=409, detail=f"Duplicate record detected: {str(e.orig)}"
        ) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/")
async def list_documents(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Fetch all the list of documents"""
    try:
        return await repo.get_all_documents(db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not fetch documents. {str(e)}") from e


@router.get("/{document_id}")
async def get_document(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Fetch a single document by id"""
    try:
        doc = await repo.get_document_by_id(document_id, db)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found.")
        return doc
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Could not fetch document.") from e


@router.get("/{document_id}/invoices")
async def get_document_invoices(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Fetch invoice by document id"""
    try:
        rows = await repo.get_invoices_with_matches(document_id, db)
        if not rows:
            return []
        return service.build_invoices_response(rows)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not fetch invoices: {str(e)}") from e


@router.get("/{document_id}/payments")
async def get_document_payments(
    document_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Fetch payment by document id"""
    try:
        rows = await repo.get_payments_by_document(document_id, db)
        if not rows:
            raise HTTPException(
                status_code=404, detail=f"No payments found for document {document_id}."
            )
        return [dict(row) for row in rows]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Could not fetch payments.") from e


@router.delete("/invoices/{invoice_id}")
async def delete_invoice(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """soft delete an invoice by its id"""
    try:
        invoice = await repo.get_invoice_by_id(invoice_id, db)
        if not invoice:
            raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found.")
        await repo.soft_delete_invoice(invoice_id, db)
        return {"message": f"Invoice {invoice_id} deleted successfully."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not delete invoice: {str(e)}") from e


@router.delete("/payments/{payment_id}")
async def delete_payment(
    payment_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """soft delete payment by payment id"""
    try:
        payment = await repo.get_payment_by_id(payment_id, db)
        if not payment:
            raise HTTPException(status_code=404, detail=f"Payment {payment_id} not found.")
        await repo.soft_delete_payment(payment_id, db)
        return {"message": f"Payment {payment_id} deleted successfully."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not delete payment: {str(e)}") from e
