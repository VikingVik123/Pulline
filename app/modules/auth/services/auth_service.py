from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from uuid import UUID, uuid4
import bcrypt
import jwt
from jose import JWTError, ExpiredSignatureError
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.modules.auth.models.auth_model import User, RefreshToken, PasswordResetToken
from app.modules.auth.schemas.auth_schemas import UserCreate, UserLogin, TokenResponse
from app.core.config import settings
from app.core.auth_dependencies import (
    hash_password, verify_password, create_access_token, create_refresh_token, decode_access_token
)
from app.core.redis_config import RedisService


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.redis = RedisService()

    async def create_user(self, user_data: UserCreate) -> User:
        """Create a new user"""
        # Check if user exists
        existing_user = await self.get_user_by_email(user_data.email)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User with this email already exists"
            )
        
        existing_username = await self.get_user_by_username(user_data.username)
        if existing_username:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already taken"
            )

        # Create new user
        hashed_password = hash_password(user_data.password)
        new_user = User(
            email=user_data.email,
            username=user_data.username,
            full_name=user_data.full_name,
            hashed_password=hashed_password,
        )
        
        self.db.add(new_user)
        await self.db.commit()
        await self.db.refresh(new_user)
        return new_user

    async def authenticate_user(self, login_data: UserLogin) -> User:
        """Authenticate user with email and password"""
        user = await self.get_user_by_email(login_data.email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        if not verify_password(login_data.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is deactivated"
            )

        return user

    async def create_auth_tokens(self, user_id: UUID, ip_address: str = None, user_agent: str = None) -> TokenResponse:
        """Create access and refresh tokens with Redis storage"""
        # Create tokens using the updated functions that store in Redis
        access_token = create_access_token(str(user_id))
        refresh_token = create_refresh_token(str(user_id))
        
        # Calculate expiry in seconds
        expires_in = settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
        
        # Store refresh token in database as backup
        refresh_token_obj = RefreshToken(
            user_id=user_id,
            token=refresh_token,
            expires_at=datetime.utcnow() + timedelta(
                days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
            ),
        )
        self.db.add(refresh_token_obj)
        await self.db.commit()
        
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in
        )

    async def refresh_access_token(self, refresh_token: str, ip_address: str = None, user_agent: str = None) -> Tuple[str, int]:
        """Refresh access token using refresh token"""
        try:
            # Check if refresh token is blacklisted in Redis
            if await self.redis.is_token_blacklisted(refresh_token):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Refresh token has been revoked"
                )
            
            # Decode refresh token
            payload = jwt.decode(
                refresh_token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM]
            )
            
            # Verify token type
            if payload.get("type") != "refresh":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token type"
                )
            
            # Get token from database
            stmt = select(RefreshToken).where(
                RefreshToken.token == refresh_token,
                RefreshToken.revoked == False
            )
            result = await self.db.execute(stmt)
            stored_token = result.scalar_one_or_none()
            
            if not stored_token:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Refresh token not found or revoked"
                )
            
            # Check if token is expired
            if stored_token.expires_at < datetime.utcnow():
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Refresh token expired"
                )
            
            # Get user
            user = await self.get_user_by_id(stored_token.user_id)
            if not user or not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="User not found or inactive"
                )
            
            # Update token info
            stored_token.ip_address = ip_address
            stored_token.user_agent = user_agent
            await self.db.commit()
            
            # Create new access token (automatically stored in Redis)
            access_token = create_access_token(str(user.id))
            expires_in = settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
            
            return access_token, expires_in
            
        except ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token expired"
            )
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token"
            )

    async def revoke_refresh_token(self, refresh_token: str) -> bool:
        """Revoke a refresh token in both Redis and database"""
        # Blacklist in Redis
        await self.redis.blacklist_token(refresh_token)
        await self.redis.delete_token(refresh_token)
        
        # Also revoke in database
        stmt = select(RefreshToken).where(RefreshToken.token == refresh_token)
        result = await self.db.execute(stmt)
        token = result.scalar_one_or_none()
        
        if token:
            token.revoked = True
            await self.db.commit()
            return True
        return False

    async def revoke_all_user_tokens(self, user_id: UUID) -> int:
        """Revoke all tokens for a user in both Redis and database"""
        # Revoke in Redis (this handles both access and refresh tokens)
        redis_count = await self.redis.revoke_all_user_tokens(user_id)
        
        # Revoke refresh tokens in database
        stmt = select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked == False
        )
        result = await self.db.execute(stmt)
        tokens = result.scalars().all()
        
        db_count = 0
        for token in tokens:
            token.revoked = True
            db_count += 1
        
        await self.db.commit()
        
        # Return total count from both sources
        return redis_count + db_count

    async def revoke_access_token(self, access_token: str) -> bool:
        """Revoke a specific access token"""
        # Blacklist in Redis
        await self.redis.blacklist_token(access_token)
        await self.redis.delete_token(access_token)
        return True

    async def update_last_login(self, user_id: UUID):
        """Update user's last login timestamp"""
        user = await self.get_user_by_id(user_id)
        if user:
            user.last_login = datetime.utcnow()
            await self.db.commit()

    async def get_user_by_id(self, user_id: UUID) -> Optional[User]:
        """Get user by ID"""
        stmt = select(User).where(User.id == user_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email"""
        stmt = select(User).where(User.email == email)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username"""
        stmt = select(User).where(User.username == username)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_current_user(self, user_id: UUID) -> User:
        """Get current user from token"""
        user = await self.get_user_by_id(user_id)
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

    async def change_password(self, user_id: UUID, new_password: str):
        """Change user password"""
        user = await self.get_user_by_id(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        user.hashed_password = hash_password(new_password)
        await self.db.commit()
        return True

    async def create_password_reset_token(self, email: str) -> str:
        """Create password reset token"""
        user = await self.get_user_by_email(email)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        # Create reset token
        token = jwt.encode(
            {
                "sub": str(user.id),
                "jti": str(uuid4()),
                "type": "reset",
                "exp": datetime.utcnow() + timedelta(hours=1)
            },
            settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM
        )
        
        # Store token in database
        reset_token = PasswordResetToken(
            user_id=user.id,
            token=token,
            expires_at=datetime.utcnow() + timedelta(hours=1)
        )
        self.db.add(reset_token)
        await self.db.commit()
        
        return token

    async def reset_password(self, token: str, new_password: str):
        """Reset password using reset token"""
        try:
            payload = jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM]
            )
            
            if payload.get("type") != "reset":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid token type"
                )
            
            # Get token from database
            stmt = select(PasswordResetToken).where(
                PasswordResetToken.token == token,
                PasswordResetToken.used == False
            )
            result = await self.db.execute(stmt)
            reset_token = result.scalar_one_or_none()
            
            if not reset_token:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid or used reset token"
                )
            
            if reset_token.expires_at < datetime.utcnow():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Reset token expired"
                )
            
            # Update password
            user = await self.get_user_by_id(reset_token.user_id)
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found"
                )
            
            user.hashed_password = hash_password(new_password)
            reset_token.used = True
            await self.db.commit()
            
            # After password reset, revoke all tokens for security
            await self.revoke_all_user_tokens(user.id)
            
            return True
            
        except ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reset token expired"
            )
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid reset token"
            )

    async def cleanup_expired_tokens(self) -> int:
        """Clean up expired refresh tokens from database"""
        stmt = select(RefreshToken).where(
            RefreshToken.expires_at < datetime.utcnow()
        )
        result = await self.db.execute(stmt)
        expired_tokens = result.scalars().all()
        
        count = len(expired_tokens)
        for token in expired_tokens:
            await self.db.delete(token)
        
        await self.db.commit()
        return count

    async def get_user_active_tokens(self, user_id: UUID) -> dict:
        """Get all active tokens for a user from Redis and database"""
        redis_tokens = await self.redis.get_user_active_tokens(user_id)
        
        db_tokens = []
        stmt = select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked == False,
            RefreshToken.expires_at > datetime.utcnow()
        )
        result = await self.db.execute(stmt)
        db_tokens = result.scalars().all()
        
        return {
            "redis_tokens": redis_tokens,
            "db_refresh_tokens": len(db_tokens),
            "total_active": len(redis_tokens) + len(db_tokens)
        }

    async def validate_token(self, token: str) -> dict:
        """Validate a token (for debugging)"""
        # Check if token is in Redis
        token_data = await self.redis.get_token_data(token)
        is_blacklisted = await self.redis.is_token_blacklisted(token)
        
        # Check if token is in database (for refresh tokens)
        stmt = select(RefreshToken).where(RefreshToken.token == token)
        result = await self.db.execute(stmt)
        db_token = result.scalar_one_or_none()
        
        return {
            "in_redis": token_data is not None,
            "is_blacklisted": is_blacklisted,
            "in_database": db_token is not None,
            "db_revoked": db_token.revoked if db_token else None,
            "db_expires_at": db_token.expires_at if db_token else None
        }