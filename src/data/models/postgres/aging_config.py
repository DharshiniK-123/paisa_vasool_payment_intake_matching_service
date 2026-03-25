from sqlalchemy import Boolean, Column, Integer, String

from src.data.clients.postgres_client import base


class AgingConfig(base):
    __tablename__ = "aging_config"

    id = Column(Integer, primary_key=True, autoincrement=True, nullable=False)
    severity = Column(String(50), nullable=False, unique=True)  # LOW/MEDIUM/HIGH/CRITICAL
    due_days_from = Column(Integer, nullable=False)
    due_days_to = Column(Integer, nullable=True)
    reminder_frequency = Column(Integer, nullable=True)
    is_active = Column(Boolean, nullable=False)
