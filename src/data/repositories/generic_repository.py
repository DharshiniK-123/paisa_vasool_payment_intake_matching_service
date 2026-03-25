from __future__ import annotations

import logging
from typing import Any, cast

from fastapi import HTTPException
from sqlalchemy import and_, delete, insert, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Delete, Update

logger = logging.getLogger(__name__)


async def commit_transaction(db: AsyncSession) -> None:
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.exception("db_commit_failed")
        raise HTTPException(status_code=500, detail="Data upload failed") from e


async def insert_instance(model: type[Any], db: AsyncSession, **kwargs: Any) -> None:
    try:
        stmt = insert(model).values(**kwargs)
        await db.execute(stmt)
        await commit_transaction(db=db)
    except IntegrityError:
        await db.rollback()
        raise
    except SQLAlchemyError:
        await db.rollback()
        logger.exception("insert_failed", extra={"model": model.__name__})
        raise


async def bulk_insert_instance(
    model: type[Any], db: AsyncSession, data: list[dict[str, Any]]
) -> None:
    try:
        stmt = insert(model)
        await db.execute(stmt, data)
        await commit_transaction(db=db)
    except SQLAlchemyError as e:
        await db.rollback()
        logger.exception("bulk_insert_failed", extra={"model": model.__name__})
        raise Exception("Bulk insertion failed") from e


async def update_instance_by_id(id: int, model: type[Any], db: AsyncSession, **kwargs: Any) -> None:
    try:
        stmt = update(model).where(model.id == id).values(**kwargs)
        result = cast(CursorResult[Any], await db.execute(stmt))
        if result.rowcount == 0:
            raise Exception("record not found")
        await commit_transaction(db=db)
    except SQLAlchemyError as e:
        await db.rollback()
        logger.exception("update_failed", extra={"model": model.__name__, "id": id})
        raise Exception("update failed") from e


async def bulk_update_instance(
    model: type[Any], db: AsyncSession, filter: dict[str, Any], data: dict[str, Any]
) -> None:
    try:
        stmt: Update = update(model)
        for key, value in filter.items():
            stmt = stmt.where(getattr(model, key, value))
        stmt = stmt.values(**data)
        results = cast(CursorResult[Any], await db.execute(stmt))
        if results.rowcount == 0:
            raise Exception("Record not found")
        await commit_transaction(db=db)
    except SQLAlchemyError as e:
        await db.rollback()
        logger.exception("bulk_update_failed", extra={"model": model.__name__})
        raise Exception("Bulk update failed") from e


async def delete_instance_by_id(id: int, model: type[Any], db: AsyncSession) -> None:
    try:
        stmt: Delete = delete(model).where(model.id == id)
        result = cast(CursorResult[Any], await db.execute(stmt))
        if result.rowcount == 0:
            raise Exception("Record not found")
        await commit_transaction(db=db)
    except SQLAlchemyError as e:
        await db.rollback()
        logger.exception("delete_failed", extra={"model": model.__name__, "id": id})
        raise Exception("delete failed") from e


async def bulk_delete_instance(model: type[Any], db: AsyncSession, ids: list[int]) -> None:
    try:
        stmt: Delete = delete(model).where(model.id.in_(ids))
        results = cast(CursorResult[Any], await db.execute(stmt))
        if results.rowcount == 0:
            raise Exception("Record not found")
        await commit_transaction(db=db)
    except SQLAlchemyError as e:
        await db.rollback()
        logger.exception("bulk_delete_failed", extra={"model": model.__name__})
        raise Exception("Bulk delete failed") from e


async def get_instance_by_id(id: int, model: type[Any], db: AsyncSession) -> Any:
    try:
        stmt = select(model).where(model.id == id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    except SQLAlchemyError as e:
        logger.exception("get_by_id_failed", extra={"model": model.__name__, "id": id})
        raise Exception("Get data failed") from e


async def get_instance_by_any(model: type[Any], db: AsyncSession, data: dict[str, Any]) -> Any:
    try:
        conditions = [getattr(model, key) == value for key, value in data.items()]
        stmt = select(model).where(and_(*conditions))
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    except SQLAlchemyError as e:
        logger.exception("get_by_any_failed", extra={"model": model.__name__})
        raise Exception("Get data failed") from e


async def bulk_get_instance(model: type[Any], db: AsyncSession, **kwargs: Any) -> Any:
    try:
        stmt = select(model)
        for key, value in kwargs.items():
            if hasattr(model, key):
                stmt = stmt.where(getattr(model, key) == value)
        result = await db.execute(stmt)
        return result.scalars().all()
    except SQLAlchemyError as e:
        logger.exception("bulk_get_failed", extra={"model": model.__name__})
        raise Exception("Get data failed") from e
