"""
Authentication routes: login, refresh, logout, MFA setup/verify.
All endpoints accept JSON body models (not bare parameters).
"""

from datetime import datetime, timezone
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.auth import (
    LoginRequest,
    MFAChallengeResponse,
    MFASetupResponse,
    MFAVerifyRequest,
    RefreshRequest,
    RefreshResponse,
    TokenResponse,
)
from src.api.schemas.common import MessageResponse
from src.infrastructure.auth.jwt_handler import (
    AuthenticationError,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_token_expires_in,
)
from src.infrastructure.auth.middleware import get_current_user
from src.infrastructure.auth.schemas import TokenData
from src.infrastructure.auth.service import (
    AuthService,
    AccountLockedError,
    InvalidCredentialsError,
    InvalidMFAError,
)
from src.infrastructure.auth.token_blacklist import token_blacklist
from src.infrastructure.database.session import get_db

logger = structlog.get_logger()
auth_service = AuthService()

router = APIRouter()


# ── Login ────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse | MFAChallengeResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Authenticate user by email and password.

    - If MFA is enabled and no mfa_code provided, returns MFA challenge.
    - If MFA is enabled and mfa_code provided, verifies TOTP and returns tokens.
    - If MFA is not enabled, returns tokens directly.
    - Returns 503 if database is not available yet.
    """
    from src.infrastructure.database.models import User

    # Query user
    try:
        result = await db.execute(select(User).where(User.email == body.email))
        user = result.scalar_one_or_none()
    except Exception as exc:
        logger.error("login_db_error", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service starting up. Please try again in a moment.",
        )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if auth_service.is_account_locked(user):
        remaining = (user.locked_until - datetime.now(timezone.utc).replace(tzinfo=None)).seconds // 60
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Account locked. Try again in {remaining} minutes.",
        )

    if not auth_service.verify_password(body.password, user.password_hash):
        auth_service.record_failed_login(user)
        await db.flush()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # MFA flow
    if user.mfa_enabled:
        if not body.mfa_code:
            # Return MFA challenge
            challenge = auth_service.create_mfa_challenge(user)
            return MFAChallengeResponse(
                mfa_required=True,
                mfa_challenge_id=challenge.mfa_challenge_id,
                message="MFA verification required",
            )
        # Verify TOTP code
        try:
            result = auth_service.verify_mfa_challenge(body.mfa_code, user)
            # This should not happen with our flow, but handle it
        except Exception:
            pass

        if not auth_service.verify_totp_code(user.mfa_secret, body.mfa_code):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid MFA code",
            )

    # Successful login
    auth_service.reset_failed_logins(user)
    user.last_login = datetime.now(timezone.utc).replace(tzinfo=None)

    token_data = TokenData(
        user_id=user.id,
        email=user.email,
        user_type=user.user_type,
        practice_id=user.practice_id,
        internal_role=user.internal_role,
        provider_role=user.provider_role,
        assigned_practice_ids=[a.practice_id for a in (user.staff_assignments or [])],
    )

    access_token = create_access_token(token_data)
    refresh_token = create_refresh_token(token_data)

    await db.commit()

    # Fetch practice_name if this is a provider user with a practice
    practice_name = None
    if user.practice_id:
        from src.infrastructure.database.models import Practice
        practice_result = await db.execute(
            select(Practice.practice_name).where(Practice.id == user.practice_id)
        )
        practice_name = practice_result.scalar_one_or_none()

    user_info = {
        "id": str(user.id),
        "email": user.email,
        "full_name": f"{user.first_name} {user.last_name}",
        "first_name": user.first_name,
        "last_name": user.last_name,
        "user_type": user.user_type,
        "internal_role": user.internal_role,
        "provider_role": user.provider_role,
        "practice_id": str(user.practice_id) if user.practice_id else None,
        "practice_name": practice_name,
        "assigned_practices": [str(pid) for pid in (token_data.assigned_practice_ids or [])],
    }

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user=user_info,
        must_change_password=getattr(user, 'must_change_password', False),
    )


# ── Token Refresh ────────────────────────────────────────────────────────

@router.post("/refresh", response_model=RefreshResponse)
async def refresh_access_token(body: RefreshRequest):
    """Validate a refresh token and issue a new access token."""
    try:
        payload = decode_token(body.refresh_token)
    except AuthenticationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )

    jti = payload.get("jti")
    if jti and await token_blacklist.is_blacklisted(jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
        )

    token_data = TokenData(
        user_id=UUID(payload["sub"]),
        email=payload["email"],
        user_type=payload["user_type"],
        practice_id=UUID(payload["practice_id"]) if payload.get("practice_id") else None,
        internal_role=payload.get("internal_role"),
        provider_role=payload.get("provider_role"),
        assigned_practice_ids=[UUID(pid) for pid in payload.get("assigned_practice_ids", [])],
    )

    access_token = create_access_token(token_data)

    return RefreshResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=get_token_expires_in("access"),
    )


# ── Logout ───────────────────────────────────────────────────────────────

@router.post("/logout", response_model=MessageResponse)
async def logout(body: RefreshRequest | None = None, current_user: dict = Depends(get_current_user)):
    """Blacklist the current user's refresh token."""
    if body and body.refresh_token:
        try:
            payload = decode_token(body.refresh_token)
            jti = payload.get("jti")
            if jti:
                from datetime import datetime as dt
                exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
                await token_blacklist.add(str(jti), exp)
        except Exception:
            pass  # Token already invalid — safe to ignore

    logger.info("user_logged_out", user_id=str(current_user.get("user_id")))
    return MessageResponse(message="Logged out successfully")


# ── MFA Setup ────────────────────────────────────────────────────────────

@router.post("/mfa/setup", response_model=MFASetupResponse)
async def setup_mfa(current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Generate a TOTP secret and provisioning URI for MFA setup."""
    from src.infrastructure.database.models import User

    result = await db.execute(select(User).where(User.id == current_user["user_id"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    setup = auth_service.setup_mfa(user)
    await db.commit()

    return MFASetupResponse(
        secret=setup.secret,
        provisioning_uri=setup.qr_code_uri,
        message="Scan the QR code with your authenticator app, then verify with a code.",
    )


# ── MFA Verify (during setup) ────────────────────────────────────────────

@router.post("/mfa/verify", response_model=MessageResponse)
async def verify_mfa_setup(body: MFAVerifyRequest, current_user: dict = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Verify the first TOTP code during MFA setup to enable MFA."""
    from src.infrastructure.database.models import User

    result = await db.execute(select(User).where(User.id == current_user["user_id"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if not auth_service.verify_mfa_setup(user, body.code):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid MFA code. Please try again.",
        )

    await db.commit()
    logger.info("mfa_enabled", user_id=str(current_user.get("user_id")))
    return MessageResponse(message="MFA has been enabled on your account.")


# ── Update Profile (PATCH /me) ────────────────────────────────────────────

class UpdateProfileRequest(BaseModel):
    first_name: str | None = None
    last_name: str | None = None


class ProfileResponse(BaseModel):
    id: str
    email: str
    first_name: str
    last_name: str
    user_type: str
    internal_role: str | None = None
    mfa_enabled: bool

    class Config:
        from_attributes = True


@router.patch("/me", response_model=ProfileResponse)
async def update_profile(
    body: UpdateProfileRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the authenticated user's profile (first/last name)."""
    from src.infrastructure.database.models import User

    result = await db.execute(select(User).where(User.id == current_user["user_id"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if body.first_name is not None:
        user.first_name = body.first_name.strip()
    if body.last_name is not None:
        user.last_name = body.last_name.strip()
    await db.commit()
    await db.refresh(user)

    logger.info("profile_updated", user_id=str(current_user.get("user_id")))
    return ProfileResponse(
        id=str(user.id),
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        user_type=user.user_type,
        internal_role=getattr(user, "internal_role", None),
        mfa_enabled=user.mfa_enabled,
    )


# ── Change Password ──────────────────────────────────────────────────────

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password", response_model=MessageResponse)
async def change_password(
    body: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change the authenticated user's password. Clears must_change_password flag."""
    from src.infrastructure.database.models import User

    result = await db.execute(select(User).where(User.id == current_user["user_id"]))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if not auth_service.verify_password(body.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )

    if len(body.new_password) < 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 10 characters.",
        )

    user.password_hash = auth_service.hash_password(body.new_password)
    user.must_change_password = False
    user.password_changed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()

    logger.info("password_changed", user_id=str(current_user.get("user_id")))
    return MessageResponse(message="Password changed successfully.")
