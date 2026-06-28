from datetime import datetime, timedelta, timezone
from uuid import uuid4, UUID
from typing import Dict, Any  # ✅ Added missing imports
import bcrypt
import asyncio
from jose import jwt
from jose import JWTError
from jose import ExpiredSignatureError
from fastapi import (
    HTTPException,
    status,
    Security,
)
from fastapi.security import (
    HTTPBearer,
    HTTPAuthorizationCredentials,
)
from passlib.hash import bcrypt as pwd_context
from app.core.config import settings
from app.core.redis_config import RedisService


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

def create_access_token(user_id: str):
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
    
    # ✅ Convert string to UUID if needed, or handle both types
    try:
        user_uuid = UUID(user_id) if isinstance(user_id, str) else user_id
        asyncio.create_task(
            redis_service.store_token(
                token,
                user_uuid,  # ✅ Pass as UUID
                "access",
                settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
            )
        )
    except Exception as e:
        # Log error but don't fail token creation
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
    
    # ✅ Convert string to UUID if needed
    try:
        user_uuid = UUID(user_id) if isinstance(user_id, str) else user_id
        asyncio.create_task(
            redis_service.store_refresh_token(
                token,
                user_uuid,  # ✅ Pass as UUID
                settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
            )
        )
    except Exception as e:
        # Log error but don't fail token creation
        print(f"Failed to store refresh token in Redis: {e}")
    
    return token

async def decode_access_token(token: str) -> Dict[str, Any]:
    """Decode and validate access token"""
    try:
        # First check Redis blacklist
        if await redis_service.is_token_blacklisted(token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
            )
        
        # Decode JWT
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        
        # Check user-level revocation
        user_id = payload.get("sub")
        if user_id:
            try:
                # Convert to UUID for Redis check
                user_uuid = UUID(user_id)
                if await redis_service.is_token_revoked_for_user(token, user_uuid):
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Token has been revoked",
                    )
            except ValueError:
                # If user_id is not a valid UUID, skip Redis check
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