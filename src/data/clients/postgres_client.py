from src.config.settings import settings
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker,AsyncSession
from sqlalchemy.orm import declarative_base


DATABASE_URL=(f"postgresql+psycopg://{settings.DB_USER}:{settings.DB_PASSWORD}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}")


engine=create_async_engine(DATABASE_URL)

AsyncSessionLocal=async_sessionmaker(bind=engine,class_=AsyncSession,autoflush=False)

base=declarative_base()

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(base.metadata.create_all)

