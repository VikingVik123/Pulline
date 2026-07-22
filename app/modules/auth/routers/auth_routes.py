from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any, List
from uuid import UUID

from app.modules.auth.services.auth_service import AuthService
from app.modules.auth.schemas.auth_schemas import (
    UserCreate, UserLogin, UserResponse, AuthResponse,
    TokenRefresh, RefreshTokenResponse, MessageResponse,
    PasswordResetRequest, PasswordResetConfirm,
    ChangePassword, UserUpdate, TokenResponse,
    VerifyEmailRequest,
    ResendVerificationRequest,
    VerificationStatusResponse
)
from app.db.database import get_db
from app.core.auth_dependencies import get_current_payload, decode_access_token
from app.core.redis_config import RedisService
from app.modules.auth.models.auth_model import User

router = APIRouter(prefix="/auth", tags=["authentication"])


# Helper dependency
async def get_current_user_from_token(
    payload: Dict[str, Any] = Depends(get_current_payload),
    db: AsyncSession = Depends(get_db)
) -> User:
    """Get current user from token payload"""
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
    
    auth_service = AuthService(db)
    user = await auth_service.get_current_user(UUID(user_id))
    return user


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Register a new user"""
    auth_service = AuthService(db)
    
    # Create user
    user = await auth_service.create_user(user_data)
    
    # Create tokens
    tokens = await auth_service.create_auth_tokens(
        user.id,
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    
    await auth_service.send_welcome_email(user.email)
    await auth_service.send_verification_email(user.id, user.email)

    return AuthResponse(
        user=UserResponse.model_validate(user),
        tokens=tokens
    )


@router.post("/login", response_model=AuthResponse)
async def login(
    login_data: UserLogin,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Login user"""
    auth_service = AuthService(db)
    
    # Authenticate user
    user = await auth_service.authenticate_user(login_data)
    
    # Update last login
    await auth_service.update_last_login(user.id)
    
    # Create tokens
    tokens = await auth_service.create_auth_tokens(
        user.id,
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    
    return AuthResponse(
        user=UserResponse.model_validate(user),
        tokens=tokens
    )


@router.post("/refresh", response_model=RefreshTokenResponse)
async def refresh_token(
    refresh_data: TokenRefresh,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Refresh access token"""
    auth_service = AuthService(db)
    
    # Check if refresh token is blacklisted in Redis
    redis_service = RedisService()
    if await redis_service.is_token_blacklisted(refresh_data.refresh_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked"
        )
    
    access_token, expires_in = await auth_service.refresh_access_token(
        refresh_data.refresh_token,
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    
    return RefreshTokenResponse(
        access_token=access_token,
        expires_in=expires_in
    )


@router.post("/logout", response_model=MessageResponse)
async def logout(
    refresh_data: TokenRefresh,
    db: AsyncSession = Depends(get_db)
):
    """Logout user by revoking refresh token"""
    auth_service = AuthService(db)
    revoked = await auth_service.revoke_refresh_token(refresh_data.refresh_token)
    
    if not revoked:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Refresh token not found"
        )
    
    return MessageResponse(
        message="Successfully logged out",
        success=True
    )


@router.post("/logout-all", response_model=MessageResponse)
async def logout_all(
    current_user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db)
):
    """Logout from all devices"""
    auth_service = AuthService(db)
    count = await auth_service.revoke_all_user_tokens(current_user.id)
    
    return MessageResponse(
        message=f"Successfully logged out from {count} devices",
        success=True
    )


@router.post("/logout-access", response_model=MessageResponse)
async def logout_access_token(
    access_token: str,
    db: AsyncSession = Depends(get_db)
):
    """Logout by revoking specific access token"""
    auth_service = AuthService(db)
    
    # Decode token to get user
    try:
        payload = await decode_access_token(access_token)
        user_id = payload.get("sub")
        if user_id:
            # Revoke the specific access token
            await auth_service.revoke_access_token(access_token)
            return MessageResponse(
                message="Access token revoked successfully",
                success=True
            )
    except HTTPException:
        # Token might be expired, but we can still blacklist it
        redis_service = RedisService()
        await redis_service.blacklist_token(access_token)
        return MessageResponse(
            message="Access token blacklisted",
            success=True
        )
    
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Invalid token"
    )


@router.get("/me", response_model=UserResponse)
async def get_current_user(
    current_user: User = Depends(get_current_user_from_token)
):
    """Get current user information"""
    return UserResponse.model_validate(current_user)


@router.put("/me", response_model=UserResponse)
async def update_current_user(
    user_update: UserUpdate,
    current_user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db)
):
    """Update current user information"""
    auth_service = AuthService(db)
    
    # Update user fields
    if user_update.email:
        existing_user = await auth_service.get_user_by_email(user_update.email)
        if existing_user and existing_user.id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already in use"
            )
        current_user.email = user_update.email
    
    if user_update.username:
        existing_user = await auth_service.get_user_by_username(user_update.username)
        if existing_user and existing_user.id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username already taken"
            )
        current_user.username = user_update.username
    
    if user_update.full_name is not None:
        current_user.full_name = user_update.full_name
    
    await db.commit()
    await db.refresh(current_user)
    
    return UserResponse.model_validate(current_user)


@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    password_data: ChangePassword,
    current_user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db)
):
    """Change user password"""
    auth_service = AuthService(db)
    await auth_service.change_password(
        current_user.id,
        password_data.new_password
    )
    
    return MessageResponse(
        message="Password changed successfully",
        success=True
    )


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(
    reset_data: PasswordResetRequest,
    db: AsyncSession = Depends(get_db)
):
    """Request password reset"""
    auth_service = AuthService(db)
    token = await auth_service.create_password_reset_token(reset_data.email)
    
    # In production, send email with reset link containing token
    await auth_service.send_password_reset_email(reset_data.email, token)
    # For now, return token in response (for testing)
    return MessageResponse(
        message=f"Password reset token generated. Token: {token}",
        success=True
    )


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(
    reset_data: PasswordResetConfirm,
    db: AsyncSession = Depends(get_db)
):
    """Reset password using token"""
    auth_service = AuthService(db)
    await auth_service.reset_password(reset_data.token, reset_data.new_password)
    
    return MessageResponse(
        message="Password reset successfully. All sessions have been logged out.",
        success=True
    )


@router.delete("/me", response_model=MessageResponse)
async def delete_account(
    current_user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db)
):
    """Delete user account"""
    # Revoke all tokens
    auth_service = AuthService(db)
    await auth_service.revoke_all_user_tokens(current_user.id)
    
    # Delete user
    await db.delete(current_user)
    await db.commit()
    
    return MessageResponse(
        message="Account deleted successfully",
        success=True
    )

# ============ HEALTH CHECK ============

@router.get("/health", response_model=Dict[str, Any])
async def health_check():
    """Check auth system health"""
    redis_service = RedisService()
    redis_healthy = await redis_service.ping()
    
    return {
        "status": "healthy" if redis_healthy else "degraded",
        "redis": "connected" if redis_healthy else "disconnected",
        "message": "Redis is operational" if redis_healthy else "Redis is not available - falling back to database-only mode"
    }

@router.post("/verify-email", response_model=MessageResponse)
async def verify_email(
    verify_data: VerifyEmailRequest,
    db: AsyncSession = Depends(get_db)
):
    """Verify email using verification token"""
    auth_service = AuthService(db)
    
    try:
        await auth_service.verify_email(verify_data.token)
        return MessageResponse(
            message="Email verified successfully! You can now log in.",
            success=True
        )
    except HTTPException as e:
        # Re-raise HTTP exceptions with their original status codes
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify email. Please try again."
        )

@router.post("/resend-verification", response_model=MessageResponse)
async def resend_verification(
    resend_data: ResendVerificationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Resend verification email"""
    auth_service = AuthService(db)
    
    try:
        await auth_service.resend_verification_token(resend_data.email)
        
        # Always return success to prevent email enumeration
        return MessageResponse(
            message="If the email exists and is not verified, a new verification email has been sent.",
            success=True
        )
    except Exception as e:
        # Still return success to prevent email enumeration
        return MessageResponse(
            message="If the email exists and is not verified, a new verification email has been sent.",
            success=False
        )

@router.get("/verification-status", response_model=VerificationStatusResponse)
async def get_verification_status(
    current_user: User = Depends(get_current_user_from_token),
    db: AsyncSession = Depends(get_db)
):
    """Get email verification status for current user"""
    auth_service = AuthService(db)
    status = await auth_service.check_verification_status(current_user.id)
    return VerificationStatusResponse(**status)