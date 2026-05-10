"""
Pydantic models for authentication request/response payloads.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    requires_mfa: bool = False
    mfa_challenge_id: UUID | None = None


class MFAChallengeResponse(BaseModel):
    mfa_challenge_id: UUID
    message: str = "MFA verification required"


class MFAVerifyRequest(BaseModel):
    mfa_challenge_id: UUID
    code: str = Field(min_length=6, max_length=8)


class MFAVerifyResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class MFASetupResponse(BaseModel):
    secret: str
    qr_code_uri: str
    backup_codes: list[str]


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    id: UUID
    email: str
    first_name: str
    last_name: str
    user_type: str
    practice_id: UUID | None = None
    internal_role: str | None = None
    provider_role: str | None = None
    is_active: bool = True
    mfa_enabled: bool = False


class TokenData(BaseModel):
    """JWT token payload structure."""
    user_id: UUID
    email: str
    user_type: str
    practice_id: UUID | None = None
    internal_role: str | None = None
    provider_role: str | None = None
    assigned_practice_ids: list[UUID] = Field(default_factory=list)
    exp: datetime | None = None
    iat: datetime | None = None
    jti: UUID | None = None