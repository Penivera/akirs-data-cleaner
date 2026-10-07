from typing import AsyncGenerator, Optional

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.models import User
from app.core.security import ACCESS_TOKEN_TYPE, decode_token

bearer_scheme = HTTPBearer(auto_error=False)

_credentials_error = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as db:
        yield db


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise _credentials_error

    try:
        payload = decode_token(credentials.credentials)
    except jwt.PyJWTError:
        raise _credentials_error

    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise _credentials_error

    subject = payload.get("sub")
    if subject is None:
        raise _credentials_error

    try:
        user_id = int(subject)
    except (TypeError, ValueError):
        raise _credentials_error

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise _credentials_error

    if payload.get("ver") != user.token_version:
        raise _credentials_error

    return user


def get_current_superuser(user: User = Depends(get_current_user)) -> User:
    if not user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superuser privileges required",
        )
    return user
