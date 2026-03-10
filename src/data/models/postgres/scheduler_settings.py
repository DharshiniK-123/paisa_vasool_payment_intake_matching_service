# src/data/models/postgres/scheduler_settings.py
from sqlalchemy import Column, Integer, Boolean
from src.data.clients.postgres_client import base

class SchedulerSettings(base):
    __tablename__ = "scheduler_settings"
    id         = Column(Integer, primary_key=True, default=1)
    run_hour   = Column(Integer, nullable=False, default=9)
    run_minute = Column(Integer, nullable=False, default=0)
    is_enabled = Column(Boolean, nullable=False, default=True)