from fastapi import APIRouter, Depends, HTTPException, status
from app.db.database import get_db
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
from app.modules.auth.services.auth_service import AuthService
from app.modules.auth.models.auth_models import User

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)

# Create a new user
@router.post("/register", response_model=UserCreateRes)
async def register_user(user_create: UserCreate, db=Depends(get_db)):
    auth_service = AuthService(db)
    return await auth_service.create_user(user_create)

@router.post("/login", response_model=UserLoginRes)
async def login_user(user_login: UserLogin, db=Depends(get_db)):
    auth_service = AuthService(db)
    return await auth_service.authenticate_user(user_login)

@router.post("/verify-email")
async def verify_email(verify_email: VerifyEmail, db=Depends(get_db)):
    auth_service = AuthService(db)
    return await auth_service.verify_email(verify_email)

@router.post("/request-password-reset")
async def request_password_reset(password_reset_request: PasswordResetRequest, db=Depends(get_db)):
    auth_service = AuthService(db)
    return await auth_service.request_password_reset(password_reset_request)

@router.post("/reset-password")
async def reset_password(reset_password: ResetPassword, db=Depends(get_db)):
    auth_service = AuthService(db)
    return await auth_service.reset_password(reset_password)

@router.post("/refresh-token", response_model=UserLoginRes)
async def refresh_token(refresh_token_request: RefreshTokenRequest, db=Depends(get_db)):
    auth_service = AuthService(db)
    return await auth_service.refresh_access_token(refresh_token_request)

