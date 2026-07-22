# app/core/auth_dependencies.py

from datetime import datetime, timedelta, timezone
from uuid import uuid4, UUID
from typing import Dict, Any
import bcrypt
import asyncio
from jose import jwt, JWTError, ExpiredSignatureError
from fastapi import (
    HTTPException,
    status,
    Security,
    Depends,
)
from fastapi.security import (
    HTTPBearer,
    HTTPAuthorizationCredentials,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.core.redis_config import RedisService
from app.db.database import get_db
from app.modules.auth.models.auth_model import User  # Only import the model, not the service


security = HTTPBearer()
redis_service = RedisService()


def hash_password(password: str) -> str:
    """Hash a password for storing."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a stored password against one provided by user."""
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))


def create_access_token(user_id: str) -> str:
    """Create a new access token"""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )

    payload = {
        "sub": user_id,
        "jti": str(uuid4()),
        "type": "access",
        "exp": expire,
    }

    token = jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    
    try:
        user_uuid = UUID(user_id) if isinstance(user_id, str) else user_id
        asyncio.create_task(
            redis_service.store_token(
                token,
                user_uuid,
                "access",
                settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
            )
        )
    except Exception as e:
        print(f"Failed to store token in Redis: {e}")
    
    return token


def create_refresh_token(user_id: str) -> str:
    """Create a new refresh token"""
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
    )
    
    payload = {
        "sub": user_id,
        "jti": str(uuid4()),
        "type": "refresh",
        "exp": expire,
    }
    
    token = jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    
    try:
        user_uuid = UUID(user_id) if isinstance(user_id, str) else user_id
        asyncio.create_task(
            redis_service.store_refresh_token(
                token,
                user_uuid,
                settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
            )
        )
    except Exception as e:
        print(f"Failed to store refresh token in Redis: {e}")
    
    return token


async def decode_access_token(token: str) -> Dict[str, Any]:
    """Decode and validate access token"""
    try:
        if await redis_service.is_blacklisted(token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
            )
        
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        
        user_id = payload.get("sub")
        if user_id:
            try:
                user_uuid = UUID(user_id)
                if await redis_service.is_token_revoked_for_user(token, user_uuid):
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Token has been revoked",
                    )
            except ValueError:
                pass
        
        return payload
        
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )


async def get_current_payload(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> Dict[str, Any]:
    """Get current token payload"""
    token = credentials.credentials
    return await decode_access_token(token)


async def get_current_user_from_token(
    payload: Dict[str, Any] = Depends(get_current_payload),
    db: AsyncSession = Depends(get_db)
) -> User:
    """Get current user from token payload - no AuthService dependency"""
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
    
    try:
        user_uuid = UUID(user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user ID in token"
        )
    
    # Query user directly instead of using AuthService
    stmt = select(User).where(User.id == user_uuid)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated"
        )
    
    return user


async def get_verified_user(
    current_user: User = Depends(get_current_user_from_token),
) -> User:
    """Dependency that ensures the current user has a verified email."""
    
    if not current_user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email verification required. Please verify your email address to access this resource."
        )
    
    return current_user