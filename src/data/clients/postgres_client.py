from src.config.settings import settings
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker,AsyncSession
from sqlalchemy.orm import declarative_base
import os

DATABASE_URL=os.getenv("DATABASE_URL")
engine=create_async_engine(DATABASE_URL)

AsyncSessionLocal=async_sessionmaker(bind=engine,class_=AsyncSession,autoflush=False)

base=declarative_base()

async def init_db():
    pass

