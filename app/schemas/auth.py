from uuid import UUID

from pydantic import BaseModel, EmailStr, field_validator

from app.core.exceptions import WeakPasswordError
from app.core.security import validate_password_strength


def _validated_password(password: str) -> str:
    error = validate_password_strength(password)
    if error:
        raise WeakPasswordError(error)
    return password


class SignupRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        return _validated_password(value)


class SignupResponse(BaseModel):
    user_id: UUID
    access_token: str
    refresh_token: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str


class RefreshRequest(BaseModel):
    refresh_token: str


class AccessTokenResponse(BaseModel):
    access_token: str


class KakaoLoginRequest(BaseModel):
    kakao_access_token: str


class KakaoLoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    is_new_user: bool


class GoogleLoginRequest(BaseModel):
    google_access_token: str


class GoogleLoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    is_new_user: bool


class MessageResponse(BaseModel):
    message: str


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class VerifyEmailRequest(BaseModel):
    token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _check_new_password(cls, value: str) -> str:
        return _validated_password(value)
