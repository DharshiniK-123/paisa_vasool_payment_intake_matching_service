from sqlalchemy import Column, Integer, String, DateTime, func
from src.data.clients.postgres_client import base


class Customer(base):
    __tablename__ = "customers"

    id          = Column(Integer, primary_key=True, autoincrement=True, nullable=False)
    name        = Column(String(100), nullable=False)
    email       = Column(String(150), nullable=False, unique=True)
    phone       = Column(String(20), nullable=True)
    created_at  = Column(DateTime(timezone=True), default=func.now())