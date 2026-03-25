from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class CustomerCreate(BaseModel):
    name: str = Field(..., max_length=100)
    email: EmailStr
    phone: str | None = Field(None, max_length=20)


class CustomerResponse(BaseModel):
    id: int
    name: str
    email: str
    phone: str | None
    created_at: datetime
    model_config = {"from_attributes": True}


class DocumentCreate(BaseModel):
    document_type: Literal["INVOICE", "PAYMENT"]
    file_name: str = Field(..., max_length=255)
    file_type: Literal["pdf", "csv", "xlsx", "png", "jpeg", "jpg", "webp"]
    storage_path: str


class DocumentResponse(BaseModel):
    id: int
    document_type: str
    file_name: str
    file_type: str
    storage_path: str
    status: str
    uploaded_at: datetime
    model_config = {"from_attributes": True}


class InvoiceDataCreate(BaseModel):
    document_id: int
    customer_id: int
    invoice_number: str = Field(..., max_length=100)
    invoice_date: date
    due_date: date
    total_amount: Decimal = Field(..., gt=0, decimal_places=2)
    paid_amount: Decimal = Field(default=Decimal("0.00"), ge=0, decimal_places=2)
    payment_status: str = Field(default="UNPAID", max_length=20)
    currency: str = Field(default="INR", max_length=10)
    gl_code: str | None = Field(None, max_length=50)


class InvoiceDataResponse(BaseModel):
    id: int
    document_id: int
    customer_id: int
    invoice_number: str
    invoice_date: date
    due_date: date
    total_amount: Decimal
    paid_amount: Decimal
    payment_status: str
    currency: str
    gl_code: str | None
    updated_at: datetime
    model_config = {"from_attributes": True}


class PaymentDetailCreate(BaseModel):
    document_id: int
    customer_id: int
    invoice_no: str = Field(..., max_length=100)
    payment_amount: Decimal = Field(..., gt=0, decimal_places=2)
    currency: str = Field(default="INR", max_length=10)
    paid_date: date
    payment_reference: str | None = Field(None, max_length=100)


class PaymentDetailResponse(BaseModel):
    id: int
    document_id: int
    customer_id: int
    invoice_no: str
    payment_amount: Decimal
    currency: str
    paid_date: date
    payment_reference: str | None
    model_config = {"from_attributes": True}


class MatchingCreate(BaseModel):
    payment_detail_id: int
    invoice_id: int | None = None
    matched_amount: Decimal = Field(..., ge=0, decimal_places=2)
    amount_pending: Decimal | None = Field(None, decimal_places=2)
    match_score: Decimal = Field(..., ge=0, le=100, decimal_places=2)
    match_status: Literal["FULL", "PARTIAL", "FAILED", "OVERPAYMENT", "DUPLICATE"]
    match_reason: str | None = None


class MatchingResponse(BaseModel):
    id: int
    payment_detail_id: int
    invoice_id: int | None
    matched_amount: Decimal
    amount_pending: Decimal | None
    match_score: Decimal
    match_status: str
    match_reason: str | None
    created_at: datetime
    model_config = {"from_attributes": True}


class AgingConfigCreate(BaseModel):
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL", "SCHEDULER"]
    due_days_from: int | None = Field(None, ge=0)
    due_days_to: int | None = Field(None, ge=1)
    reminder_frequency: int | None = Field(None, ge=1)
    is_active: bool = True
    run_hour: int | None = Field(None, ge=0, le=23)
    run_minute: int | None = Field(None, ge=0, le=59)
    message_template: str | None = None


class AgingConfigUpdate(BaseModel):
    due_days_from: int | None = Field(None, ge=0)
    due_days_to: int | None = Field(None, ge=1)
    reminder_frequency: int | None = Field(None, ge=1)
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL", "SCHEDULER"]
    is_active: bool
    run_hour: int | None = Field(None, ge=0, le=23)
    run_minute: int | None = Field(None, ge=0, le=59)


class AgingConfigResponse(BaseModel):
    id: int
    severity: str
    due_days_from: int | None = None
    due_days_to: int | None = None
    reminder_frequency: int | None = None
    is_active: bool
    run_hour: int | None = None
    run_minute: int | None = None
    message_template: str | None = None
    model_config = {"from_attributes": True}


class ReminderLogCreate(BaseModel):
    customer_id: int
    invoice_id: int
    severity: Literal["MEDIUM", "HIGH", "CRITICAL"]
    subject: str = Field(..., max_length=255)
    body: str
    channel: Literal["EMAIL"] = "EMAIL"
    status: Literal["SENT", "FAILED"]


class ReminderLogResponse(BaseModel):
    id: int
    customer_id: int
    invoice_id: int
    severity: str
    subject: str
    body: str
    channel: str
    status: str
    sent_at: datetime
    customer_name: str | None = None
    customer_email: str | None = None
    invoice_number: str | None = None
    model_config = {"from_attributes": True}
