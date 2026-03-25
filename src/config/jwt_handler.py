import uuid
from datetime import datetime, timedelta

from jose import JWTError, jwt

from src.config.settings import settings


def create_access_token(payload: dict):
    to_encode = payload.copy()
    expire = datetime.now() + timedelta(minutes=settings.JWT_EXPIRATION_MINUTES)
    jti = str(uuid.uuid4())
    to_encode.update({"exp": expire, "jti": jti, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt, jti


def create_refresh_token(payload: dict):
    to_encode = payload.copy()
    expire = datetime.now() + timedelta(days=settings.JWT_REFRESH_SECRET_KEY_EXPIRATION_DAYS)
    jti = str(uuid.uuid4())
    to_encode.update({"exp": expire, "jti": jti, "type": "refresh"})
    encoded_jwt = jwt.encode(
        to_encode, settings.JWT_REFRESH_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt, jti


def verify_access_token(token: str):
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "access":
            return None
        return payload
    except JWTError:
        return None


def verify_refresh_token(token: str):
    if not token:
        return None
    try:
        payload = jwt.decode(
            token, settings.JWT_REFRESH_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        if payload.get("type") != "refresh":
            return None
        return payload
    except JWTError:
        return None
