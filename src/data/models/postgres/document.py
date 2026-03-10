from sqlalchemy import Column, Integer, String, DateTime, func, ForeignKey
from src.data.clients.postgres_client import base


class Document(base):
    __tablename__ = "documents"

    id           = Column(Integer, primary_key=True, autoincrement=True, nullable=False)
    document_type = Column(String(50), nullable=False) #INVOICE/PAYMENT
    file_name    = Column(String(255), nullable=False)
    file_type    = Column(String(20), nullable=False) # pdf/csv/xlsx
    storage_path = Column(String, nullable=False)  
    status       = Column(String(50), nullable=False)#UPLOADED/PARSED/FAILED
    uploaded_at  = Column(DateTime(timezone=True), default=func.now())