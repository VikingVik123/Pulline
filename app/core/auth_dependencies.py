from datetime import datetime, timedelta, timezone
from uuid import uuid4

import bcrypt

from jose import jwt
from jose import JWTError
from jose import ExpiredSignatureError
from passlib.hash import bcrypt

from fastapi import (
    HTTPException,
    status,
    Security,
)

from fastapi.security import (
    HTTPBearer,
    HTTPAuthorizationCredentials,
)

from app.core.config import settings

security = HTTPBearer()


def hash_password(password: str) -> str:
    """Hash a password for storing."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a stored password against one provided by user."""
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def create_access_token(user_id: str,):
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )

    payload = {
        "sub": user_id,
        "jti": str(uuid4()),
        "type": "access",
        "exp": expire,
    }

    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )

def decode_access_token(token: str):
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )

    except ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Token expired",
        )

    except JWTError:
        raise HTTPException(
            status_code=401,
            detail="Invalid token",
        )

async def get_current_payload(
    credentials: HTTPAuthorizationCredentials = Security(
        security
    ),
):
    token = credentials.credentials

    return decode_access_token(token)