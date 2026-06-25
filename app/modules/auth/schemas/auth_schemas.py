from pydantic import BaseModel, EmailStr
from typing import Optional

class UserCreate(BaseModel):
    email: EmailStr
    password: str

class UserCreateRes(BaseModel):
    message: str
    id: str
    email_verified: bool

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserLoginRes(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None

class VerifyEmail(BaseModel):
    email: EmailStr
    verification_token: str

class PasswordResetRequest(BaseModel):
    email: EmailStr

class ResetPassword(BaseModel):
    reset_token: str
    new_password: str

class RefreshTokenRequest(BaseModel):
    refresh_token: str
