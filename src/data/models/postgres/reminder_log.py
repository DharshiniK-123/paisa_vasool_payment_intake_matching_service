from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func, Text
from src.data.clients.postgres_client import base


class ReminderLog(base):
    __tablename__ = "reminder_log"

    id           = Column(Integer, primary_key=True, autoincrement=True, nullable=False)
    customer_id  = Column(Integer, ForeignKey("customers.id"), nullable=False)
    invoice_id   = Column(Integer, ForeignKey("invoice_data.id"), nullable=False)
    severity     = Column(String(50), nullable=False)#LOW/MEDIUM/HIGH/CRITICAL
    subject      = Column(String(255), nullable=False)
    body         = Column(Text, nullable=False)             
    channel      = Column(String(50), nullable=False, default="EMAIL")
    status       = Column(String(50), nullable=False)#SENT/FAILED
    sent_at      = Column(DateTime(timezone=True), default=func.now())