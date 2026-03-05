from sqlalchemy import Column, Integer, String, Date, DateTime, Numeric, ForeignKey, func
from src.data.clients.postgres_client import base


class InvoiceData(base):
    __tablename__ = "invoice_data"

    id              = Column(Integer, primary_key=True, autoincrement=True, nullable=False)
    document_id     = Column(Integer, ForeignKey("documents.id"), nullable=False)
    customer_id     = Column(Integer, ForeignKey("customers.id"), nullable=False)
    invoice_number  = Column(String(100), nullable=False, unique=True)
    invoice_date    = Column(Date, nullable=False)
    due_date        = Column(Date, nullable=False)
    total_amount    = Column(Numeric(12, 2), nullable=False)
    paid_amount     = Column(Numeric(12, 2), nullable=False, default=0.00)     
    payment_status  = Column(String(20), nullable=False, default="UNPAID")
    currency        = Column(String(10), nullable=False, default="INR")
    gl_code         = Column(String(50), nullable=True)
    updated_at      = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())