from sqlalchemy import Boolean, Column, Integer, String
from src.data.clients.postgres_client import base


class AgingConfig(base):
    __tablename__ = "aging_config"

    id                  = Column(Integer, primary_key=True, autoincrement=True, nullable=False)
    severity            = Column(String(50), nullable=False, unique=True) #LOW/MEDIUM/HIGH/CRITICAL
    due_days_from       = Column(Integer, nullable=False)  
    due_days_to         = Column(Integer, nullable=True)  
    reminder_frequency  = Column(Integer, nullable=False)
    is_active           = Column(Boolean,nullable=False)
    run_hour            = Column(Integer, nullable=True)  
    run_minute          = Column(Integer, nullable=True)
    message_template   = Column(String, nullable=True)