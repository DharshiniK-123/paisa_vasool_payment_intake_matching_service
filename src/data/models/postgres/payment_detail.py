
from sqlalchemy import Column, Integer, String, Date, Numeric, ForeignKey, Boolean, UniqueConstraint
from src.data.clients.postgres_client import base


class PaymentDetail(base):
    __tablename__ = "payment_details"

    id                 = Column(Integer, primary_key=True, autoincrement=True, nullable=False)
    document_id        = Column(Integer, ForeignKey("documents.id"), nullable=False)
    customer_id        = Column(Integer, ForeignKey("customers.id"), nullable=False)
    invoice_no         = Column(String(100), nullable=False)
    payment_amount     = Column(Numeric(12, 2), nullable=False)
    currency           = Column(String(10), nullable=False, default="INR")
    paid_date          = Column(Date, nullable=False)
    payment_reference  = Column(String(100), nullable=True)
    is_deleted         = Column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint(
            "invoice_no",
            "payment_reference",
            name="unique_invoice_payment_reference"
        ),
    )
