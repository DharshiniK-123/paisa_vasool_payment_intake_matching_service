from pydantic import BaseModel, EmailStr, Field
from typing import Optional, Literal
from datetime import date, datetime
from decimal import Decimal

class CustomerCreate(BaseModel):
    name   : str       = Field(..., max_length=100)
    email  : EmailStr
    phone  : Optional[str] = Field(None, max_length=20)

class CustomerResponse(BaseModel):
    id         : int
    name       : str
    email      : str
    phone      : Optional[str]
    created_at : datetime
    model_config = {"from_attributes": True}


class DocumentCreate(BaseModel):
    document_type : Literal["INVOICE", "PAYMENT"]
    file_name     : str = Field(..., max_length=255)
    file_type     : Literal["pdf", "csv", "xlsx","png","jpeg","jpg","webp"]
    storage_path  : str

class DocumentResponse(BaseModel):
    id            : int
    document_type : str
    file_name     : str
    file_type     : str
    storage_path  : str
    status        : str
    uploaded_at   : datetime
    model_config = {"from_attributes": True}

class InvoiceDataCreate(BaseModel):
    document_id    : int
    customer_id    : int
    invoice_number : str     = Field(..., max_length=100)
    invoice_date   : date
    due_date       : date
    total_amount   : Decimal = Field(..., gt=0, decimal_places=2)
    paid_amount    : Decimal = Field(default=Decimal("0.00"), ge=0, decimal_places=2)  
    payment_status : str     = Field(default="UNPAID", max_length=20)
    currency       : str     = Field(default="INR", max_length=10)
    gl_code        : Optional[str] = Field(None, max_length=50)

class InvoiceDataResponse(BaseModel):
    id             : int
    document_id    : int
    customer_id    : int
    invoice_number : str
    invoice_date   : date
    due_date       : date
    total_amount   : Decimal
    paid_amount    : Decimal  
    payment_status : str 
    currency       : str
    gl_code        : Optional[str]
    updated_at     : datetime
    model_config = {"from_attributes": True}



class PaymentDetailCreate(BaseModel):
    document_id       : int
    customer_id       : int
    invoice_no        : str     = Field(..., max_length=100)
    payment_amount    : Decimal = Field(..., gt=0, decimal_places=2)
    currency          : str     = Field(default="INR", max_length=10)
    paid_date         : date
    payment_reference : Optional[str] = Field(None, max_length=100)

class PaymentDetailResponse(BaseModel):
    id                : int
    document_id       : int
    customer_id       : int
    invoice_no        : str
    payment_amount    : Decimal
    currency          : str
    paid_date         : date
    payment_reference : Optional[str]
    model_config = {"from_attributes": True}

class MatchingCreate(BaseModel):
    payment_detail_id : int
    invoice_id        : Optional[int] = None                                       
    matched_amount    : Decimal = Field(..., ge=0, decimal_places=2)                
    amount_pending    : Optional[Decimal] = Field(None, decimal_places=2)
    match_score       : Decimal = Field(..., ge=0, le=100, decimal_places=2)
    match_status      : Literal["FULL", "PARTIAL", "FAILED", "OVERPAYMENT", "DUPLICATE"]  
    match_reason      : Optional[str] = None                                        

class MatchingResponse(BaseModel):
    id                : int
    payment_detail_id : int
    invoice_id        : Optional[int]       
    matched_amount    : Decimal
    amount_pending    : Optional[Decimal]
    match_score       : Decimal
    match_status      : str
    match_reason      : Optional[str]       
    created_at        : datetime
    model_config = {"from_attributes": True}

class AgingConfigCreate(BaseModel):
    severity           : Literal["LOW", "MEDIUM", "HIGH", "CRITICAL", "SCHEDULER"]
    due_days_from      : Optional[int] = Field(None, ge=0)
    due_days_to        : Optional[int] = Field(None, ge=1)
    reminder_frequency : Optional[int] = Field(None, ge=1)
    is_active          : bool=True
    run_hour           : Optional[int] = Field(None, ge=0, le=23)
    run_minute         : Optional[int] = Field(None, ge=0, le=59)
    message_template   : Optional[str] = None


class AgingConfigUpdate(BaseModel):
    due_days_from      : Optional[int] = Field(None, ge=0)
    due_days_to        : Optional[int] = Field(None, ge=1)
    reminder_frequency : Optional[int] = Field(None, ge=1)
    severity           : Literal["LOW", "MEDIUM", "HIGH", "CRITICAL", "SCHEDULER"]
    is_active          : bool
    run_hour           : Optional[int] = Field(None, ge=0, le=23)
    run_minute         : Optional[int] = Field(None, ge=0, le=59)


class AgingConfigResponse(BaseModel):
    id                 : int
    severity           : str
    due_days_from      : Optional[int] = None
    due_days_to        : Optional[int] = None
    reminder_frequency : Optional[int] = None
    is_active          : bool
    run_hour           : Optional[int] = None
    run_minute         : Optional[int] = None
    message_template   : Optional[str] = None
    model_config = {"from_attributes": True}

class ReminderLogCreate(BaseModel):
    customer_id : int
    invoice_id  : int
    severity    : Literal[ "MEDIUM", "HIGH", "CRITICAL"]
    subject     : str = Field(..., max_length=255)
    body        : str
    channel     : Literal["EMAIL"] = "EMAIL"
    status      : Literal["SENT", "FAILED"]

class ReminderLogResponse(BaseModel):
    id          : int
    customer_id : int
    invoice_id  : int
    severity    : str
    subject     : str
    body        : str
    channel     : str
    status      : str
    sent_at     : datetime
    customer_name:  Optional[str] = None
    customer_email: Optional[str] = None
    invoice_number: Optional[str] = None
    model_config = {"from_attributes": True}