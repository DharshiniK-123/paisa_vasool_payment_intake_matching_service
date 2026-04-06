from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from src.core.enums import MatchStatus


class MatchingCreate(BaseModel):
    payment_detail_id: int
    invoice_id: int | None = None
    matched_amount: Decimal
    amount_pending: Decimal | None = None
    match_score: Decimal
    match_status: MatchStatus
    match_reason: str | None = None


class SuggestedMatchResponse(BaseModel):
    match_id:        int
    payment_id:      int
    invoice_id:      int
    invoice_number:  str
    invoice_amount:  Decimal
    payment_amount:  Decimal
    matched_amount:  Decimal
    amount_pending:  Decimal | None
    match_score:     Decimal
    match_reason:    str | None
    created_at:      datetime
    model_config = {"from_attributes": True}


class ManualAssignRequest(BaseModel):
    invoice_id: int
