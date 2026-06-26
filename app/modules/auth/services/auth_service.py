from app.core.config import settings
from app.db.database import AsyncSession, get_db
from app.modules.auth.models.auth_models import User
from app.core.auth_dependencies import (
    hash_password, 
    verify_password, 
    create_access_token, 
    decode_access_token,
    get_current_payload
    )
from sqlalchemy.future import select
from app.modules.auth.schemas.auth_schemas import (
    UserCreate,
    UserLogin,
    UserCreateRes,
    UserLoginRes,
    VerifyEmail,
    PasswordResetRequest,
    ResetPassword,
    RefreshTokenRequest,
)
from app.core.email import EmailService
from datetime import datetime, timedelta, timezone
import secrets
from fastapi import HTTPException

class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_user(self, user_create: UserCreate,) -> UserCreateRes:
        hashed_password = hash_password(user_create.password)
        verification_token = secrets.token_urlsafe(32)
        verification_token_expiry = (datetime.now(timezone.utc) + timedelta(hours=24))

        new_user = User(
            email=user_create.email,
            hashed_password=hashed_password,
            email_verified=False,
            verification_token=verification_token,
            verification_token_expiry=verification_token_expiry,
        )

        self.db.add(new_user)
        await self.db.commit()
        await self.db.refresh(new_user)

        return UserCreateRes(
            message="User created successfully. Please check your email to verify your account.",
            id=str(new_user.id),
            email_verified=new_user.email_verified,
    )
    
    async def authenticate_user(self, user_login: UserLogin) -> UserLoginRes:
        """
        Authenticate a user and return an access token.
        """

        user = await self.db.scalar(
            select(User).where(
                User.email == user_login.email
            )
        )

        if not user:
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password",
            )

        if not user.email_verified:
            raise HTTPException(
                status_code=403,
                detail="Please verify your email first",
            )

        if not verify_password(user_login.password, user.hashed_password):
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password",
            )

        access_token = create_access_token(user_id=str(user.id))

        # Optional: update last login
        user.last_login = datetime.now(timezone.utc)

        await self.db.commit()

        return UserLoginRes(access_token=access_token,)
        

    
    async def verify_email(self, verify_email: VerifyEmail) -> str:
        """Verify a user's email using the verification token."""
        # Fetch the user from the database
        result = await self.db.execute(select(User).where(User.email == verify_email.email))
        user = result.scalar_one_or_none()

        if not user:
            raise Exception("User not found")

        # Check if the verification token matches and is not expired
        if user.verification_token != verify_email.verification_token:
            raise Exception("Invalid verification token")
        
        if user.verification_token_expiry < datetime.now(timezone.utc):
            raise Exception("Verification token has expired")

        # Mark the email as verified
        user.email_verified = True
        user.verification_token = None
        user.verification_token_expiry = None

        await self.db.commit()
        await self.db.refresh(user)

        return "Email verified successfully"
    
    async def request_password_reset(self, password_reset_request: PasswordResetRequest) -> str:
        """Request a password reset and send a reset email."""
        # Fetch the user from the database
        result = await self.db.execute(select(User).where(User.email == password_reset_request.email))
        user = result.scalar_one_or_none()

        if not user:
            raise Exception("User not found")

        # Generate a reset token and expiry
        reset_token = "some_generated_token"  # You should implement a proper token generation
        reset_token_expiry = datetime.now(timezone.utc) + timedelta(hours=1)

        # Update the user with the reset token and expiry
        user.reset_token = reset_token
        user.reset_token_expiry = reset_token_expiry

        await self.db.commit()
        await self.db.refresh(user)

        # Send password reset email
        email_service = EmailService()
        await email_service.send_password_reset_email(user.email, user.username, user.reset_token)

        return "Password reset email sent successfully"
    
    async def reset_password(self, reset_password: ResetPassword) -> str:
        """Reset a user's password using the reset token."""
        # Fetch the user from the database
        result = await self.db.execute(select(User).where(User.reset_token == reset_password.reset_token))
        user = result.scalar_one_or_none()

        if not user:
            raise Exception("Invalid reset token")

        # Check if the reset token is expired
        if user.reset_token_expiry < datetime.now(timezone.utc):
            raise Exception("Reset token has expired")

        # Hash the new password and update the user
        hashed_password = hash_password(reset_password.new_password)
        user.hashed_password = hashed_password
        user.reset_token = None
        user.reset_token_expiry = None

        await self.db.commit()
        await self.db.refresh(user)

        return "Password reset successfully"
    
    async def refresh_access_token(self, refresh_token_request: RefreshTokenRequest) -> UserLoginRes:
        """Refresh the access token using a refresh token."""
        # Decode the refresh token to get the user ID
        payload = decode_access_token(refresh_token_request.refresh_token)
        user_id: str = payload.get("sub")

        if not user_id:
            raise Exception("Invalid refresh token")

        # Fetch the user from the database
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            raise Exception("User not found")

        # Create a new access token
        access_token = create_access_token(data={"sub": str(user.id)})

        return UserLoginRes(access_token=access_token)
    
    async def get_current_user(self, token: str) -> User:
        """Get the current user from the JWT token."""
        payload = decode_access_token(token)
        user_id: str = payload.get("sub")

        if not user_id:
            raise Exception("Invalid token: missing user ID")

        # Fetch the user from the database
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            raise Exception("User not found")

        return user