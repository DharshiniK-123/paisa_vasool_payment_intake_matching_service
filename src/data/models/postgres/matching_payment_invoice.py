from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, Text, func
from src.data.clients.postgres_client import base


class MatchingPaymentInvoice(base):
    __tablename__ = "matching_payment_invoice"

    id                = Column(Integer, primary_key=True, autoincrement=True, nullable=False)
    payment_detail_id = Column(Integer, ForeignKey("payment_details.id"), nullable=False)
    invoice_id        = Column(Integer, ForeignKey("invoice_data.id"), nullable=True)
    matched_amount    = Column(Numeric(12, 2), nullable=False)
    amount_pending    = Column(Numeric(12, 2), nullable=True)
    match_score       = Column(Numeric(5, 2), nullable=False) 
    match_status      = Column(String(50), nullable=False)# FULL/PARTIAL/ FAILED
    match_reason      = Column(Text, nullable=True)
    created_at        = Column(DateTime(timezone=True), default=func.now())