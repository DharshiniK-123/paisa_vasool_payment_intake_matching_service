from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rest.dependencies import get_current_user, get_db
from src.core.services.matching import matching_service as service
from src.core.services.matching.manual_review_service import (
    approve_match,
    reject_match,
)
from src.schemas.payment_intake_matching import MatchingResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/matching", tags=["Matching"])


@router.get("/payment/{payment_id}", response_model=list[MatchingResponse])
async def get_matches_by_payment(
    payment_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Retrieve all invoice matches for a given payment."""
    try:
        matches = await service.get_matches_by_payment(payment_id, db)
        if not matches:
            raise HTTPException(
                status_code=404, detail=f"No matches found for payment {payment_id}."
            )
        return matches
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Could not fetch payment matches.") from e


@router.get("/invoice/{invoice_id}", response_model=list[MatchingResponse])
async def get_matches_by_invoice(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Retrieve all payment matches for a given invoice."""
    try:
        matches = await service.get_matches_by_invoice(invoice_id, db)
        if not matches:
            raise HTTPException(
                status_code=404, detail=f"No matches found for invoice {invoice_id}."
            )
        return matches
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Could not fetch invoice matches.") from e


@router.get("/dashboard/summary")
async def get_dashboard_summary(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await service.get_dashboard_summary(db)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Could not load dashboard summary.") from e


@router.get("/dashboard/unmatched-payments")
async def get_unmatched_payments(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await service.get_unmatched_payments(db)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Could not fetch unmatched payments.") from e


@router.get("/dashboard/unmatched-invoices")
async def get_unmatched_invoices(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await service.get_unmatched_invoices(db)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Could not fetch unmatched invoices.") from e


@router.get("/invoice-detail/{invoice_id}")
async def get_invoice_detail(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
):
    try:
        data = await service.get_invoice_detail(invoice_id, db)
        if not data:
            raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found.")
        return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Could not fetch invoice detail: {str(e)}"
        ) from e


@router.get("/payment-detail/{payment_id}")
async def get_payment_detail(
    payment_id: int,
    db: AsyncSession = Depends(get_db),
):
    try:
        data = await service.get_payment_detail(payment_id, db)
        if not data:
            raise HTTPException(status_code=404, detail=f"Payment {payment_id} not found.")
        return data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Could not fetch payment detail: {str(e)}"
        ) from e


@router.get("/dashboard/recent")
async def get_recent_matches(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        if limit <= 0 or limit > 100:
            raise HTTPException(status_code=400, detail="Limit must be between 1 and 100.")
        return await service.get_recent_matches(limit, db)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Could not fetch recent matches.") from e


@router.get("/dashboard/discrepancies")
async def get_discrepancies(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await service.get_discrepancies(db)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Could not fetch discrepancies.") from e


@router.get("/pending-review")
async def get_pending_review(
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        return await service.get_pending_review(db)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail="Could not fetch pending review matches."
        ) from e


@router.patch(
    "/payment/{payment_id}/matches/{match_id}/approve",
    response_model=MatchingResponse,
)
async def approve_suggested_match(
    payment_id: int,
    match_id:   int,
    db:         AsyncSession = Depends(get_db),
    user:       dict         = Depends(get_current_user),
):
    try:
        return await approve_match(match_id=match_id, payment_id=payment_id, db=db)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Could not approve match.") from e


@router.patch(
    "/payment/{payment_id}/matches/{match_id}/reject",
    response_model=MatchingResponse,
)
async def reject_suggested_match(
    payment_id: int,
    match_id:   int,
    db:         AsyncSession = Depends(get_db),
    user:       dict         = Depends(get_current_user),
):
    try:
        return await reject_match(match_id=match_id, payment_id=payment_id, db=db)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="Could not reject match.") from e


class ManualAssignRequest(BaseModel):
    invoice_id: int


