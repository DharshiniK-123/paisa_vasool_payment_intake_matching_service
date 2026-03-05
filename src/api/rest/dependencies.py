from src.data.clients.postgres_client import AsyncSessionLocal
from fastapi import Depends, HTTPException, Request
from src.config.jwt_handler import verify_access_token


async def get_db():
    async with AsyncSessionLocal() as Session:
        yield Session

async def get_current_user(request: Request):
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
    else:
        raise HTTPException(status_code=401, detail="Access token missing")
    payload = verify_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload


