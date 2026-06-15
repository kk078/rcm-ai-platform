"""Auth request/response schemas for the login flow and MFA."""

from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)
    mfa_code: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict
    must_change_password: bool = False


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class MFASetupResponse(BaseModel):
    secret: str
    provisioning_uri: str
    message: str


class MFAVerifyRequest(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class MFAChallengeResponse(BaseModel):
    mfa_required: bool = True
    mfa_challenge_id: UUID | None = None
    message: str = "MFA verification required"