from typing import List, Type
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError,SQLAlchemyError
from sqlalchemy import and_, insert,select,update,delete
async def commit_transaction(db:AsyncSession):

    try:
        await db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Data upload failed")
    
async def insert_instance(model:Type,db:AsyncSession,**kwargs):
    try:
        stmt=insert(model).values(**kwargs)
        await db.execute(stmt)
        await commit_transaction(db=db)
    except IntegrityError:
        await db.rollback()
        raise
    except SQLAlchemyError as e:
        await db.rollback()
        raise


async def bulk_insert_instance(model:Type,db:AsyncSession,data:list[dict]):
    try:
        stmt=insert(model)
        await db.execute(stmt,data)
        await commit_transaction(db=db)
    except SQLAlchemyError as e:
        await db.rollback()
        raise Exception(f"Bulk insertion failed ")



async def update_instance_by_id(id:int,model:Type,db:AsyncSession,**kwargs):
    try:
        stmt=update(model).where(model.id==id).values(**kwargs)
        result=await db.execute(stmt)
        if result.rowcount==0:
            raise Exception("record not found")
        await commit_transaction(db=db)
    except SQLAlchemyError as e:
        await db.rollback()
        raise Exception(f"update failed")
    

async def bulk_update_instance(model:Type,db:AsyncSession,filter:dict,data:dict):
    try:
        stmt=update(model)
        for key,value in filter.items():
            stmt=stmt.where(getattr(model,key,value))
        stmt=stmt.values(**data)
        results=await db.execute(stmt)

        if results.rowcount==0:
            raise Exception("Record not found")
        await commit_transaction(db=db)
    except SQLAlchemyError as e:
        await db.rollback()
        raise Exception(f"Bulk update failed")



async def delete_instance_by_id(id:int, model:Type,db:AsyncSession):
    try:
        stmt=delete(model).where(model.id==id)
        result=await db.execute(stmt)
        if result.rowcount==0:
            raise Exception("Record not found")
        await commit_transaction(db=db)
    except SQLAlchemyError as e:
        await db.rollback()
        raise Exception(f"delete failed")

async def bulk_delete_instance(model:Type,db:AsyncSession,ids:List[int]):
    try:
        stmt=delete(model).where(model.id.in_(ids))
        
        results=await db.execute(stmt)

        if results.rowcount==0:
            raise Exception("Record not found")
        
        await commit_transaction(db=db)

    except SQLAlchemyError as e:
        await db.rollback()
        raise Exception(f"Bulk delete failed")


async def get_instance_by_id(id:int,model:Type,db:AsyncSession):
    try:
        stmt=select(model).where(model.id==id)
        result=await db.execute(stmt)
       
        return result.scalar_one_or_none()
    except SQLAlchemyError as e:
        raise Exception(f"Get data failed ")
    

async def get_instance_by_any(model:Type,db:AsyncSession,data:dict):
    try:
        conditions=[]
        for key,value in data.items():
            column=getattr(model,key)
            conditions.append(column==value)
        
        stmt=select(model).where(and_(*conditions))
        result=await db.execute(stmt)
        
        return result.scalar_one_or_none()
    except SQLAlchemyError as e:
        raise Exception(f"Get data failed ")
    
async def bulk_get_instance(model:Type,db:AsyncSession,**kwargs):
    try:
        stmt=select(model)
        for key,value in kwargs.items():
            if hasattr(model,key):
                stmt=stmt.where(getattr(model,key)==value)
        result=await db.execute(stmt)
        
        return result.scalars().all()
    except SQLAlchemyError as e:
        raise Exception(f"Get data failed")

