"""
User management routes — admin-only CRUD for internal staff accounts.
All endpoints require company_admin role.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.common import MessageResponse
from src.infrastructure.auth.middleware import get_current_user, require_role
from src.infrastructure.auth.service import AuthService
from src.infrastructure.database.session import get_db

logger = structlog.get_logger()
auth_service = AuthService()
router = APIRouter()

INTERNAL_ROLES = [
    "company_admin", "billing_specialist", "coder",
    "ar_specialist", "payment_poster", "denial_manager", "viewer",
]


# ── Schemas ──────────────────────────────────────────────────────────────

class UserOut(BaseModel):
    id: UUID
    email: str
    first_name: str
    last_name: str
    full_name: str
    internal_role: Optional[str]
    is_active: bool
    mfa_enabled: bool
    last_login: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class CreateUserRequest(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    internal_role: str
    password: str

    @field_validator("internal_role")
    @classmethod
    def valid_role(cls, v: str) -> str:
        if v not in INTERNAL_ROLES:
            raise ValueError(f"Role must be one of: {', '.join(INTERNAL_ROLES)}")
        return v

    @field_validator("password")
    @classmethod
    def strong_password(cls, v: str) -> str:
        if len(v) < 10:
            raise ValueError("Password must be at least 10 characters")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain an uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain a lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain a digit")
        return v


class UpdateUserRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    internal_role: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("internal_role")
    @classmethod
    def valid_role(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in INTERNAL_ROLES:
            raise ValueError(f"Role must be one of: {', '.join(INTERNAL_ROLES)}")
        return v


class ChangeUserPasswordRequest(BaseModel):
    new_password: str

    @field_validator("new_password")
    @classmethod
    def strong_password(cls, v: str) -> str:
        if len(v) < 10:
            raise ValueError("Password must be at least 10 characters")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain an uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain a lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain a digit")
        return v


# ── Helper: require admin ─────────────────────────────────────────────────

def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("internal_role") != "company_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only company administrators can manage users",
        )
    return current_user


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.get("", response_model=list[UserOut])
async def list_users(
    current_user: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all internal staff users."""
    from src.infrastructure.database.models import User
    result = await db.execute(
        select(User)
        .where(User.user_type == "internal")
        .order_by(User.created_at.desc())
    )
    users = result.scalars().all()
    return [
        UserOut(
            id=u.id,
            email=u.email,
            first_name=u.first_name or "",
            last_name=u.last_name or "",
            full_name=f"{u.first_name or ''} {u.last_name or ''}".strip(),
            internal_role=u.internal_role,
            is_active=u.is_active,
            mfa_enabled=u.mfa_enabled,
            last_login=u.last_login,
            created_at=u.created_at,
        )
        for u in users
    ]


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: CreateUserRequest,
    current_user: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new internal staff user."""
    from src.infrastructure.database.models import User

    # Check email not already taken
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    user = User(
        email=body.email,
        password_hash=auth_service.hash_password(body.password),
        first_name=body.first_name.strip(),
        last_name=body.last_name.strip(),
        user_type="internal",
        internal_role=body.internal_role,
        is_active=True,
        mfa_enabled=False,
        password_changed_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    logger.info("user_created", new_user_id=str(user.id), by=str(current_user["user_id"]))
    return UserOut(
        id=user.id,
        email=user.email,
        first_name=user.first_name or "",
        last_name=user.last_name or "",
        full_name=f"{user.first_name or ''} {user.last_name or ''}".strip(),
        internal_role=user.internal_role,
        is_active=user.is_active,
        mfa_enabled=user.mfa_enabled,
        last_login=user.last_login,
        created_at=user.created_at,
    )


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: UUID,
    body: UpdateUserRequest,
    current_user: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update a user's name, role, or active status."""
    from src.infrastructure.database.models import User

    result = await db.execute(select(User).where(User.id == user_id, User.user_type == "internal"))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Prevent admin from deactivating themselves
    if body.is_active is False and user_id == current_user["user_id"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot deactivate your own account")

    if body.first_name is not None:
        user.first_name = body.first_name.strip()
    if body.last_name is not None:
        user.last_name = body.last_name.strip()
    if body.internal_role is not None:
        user.internal_role = body.internal_role
    if body.is_active is not None:
        user.is_active = body.is_active

    user.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    await db.refresh(user)

    logger.info("user_updated", target_user_id=str(user_id), by=str(current_user["user_id"]))
    return UserOut(
        id=user.id,
        email=user.email,
        first_name=user.first_name or "",
        last_name=user.last_name or "",
        full_name=f"{user.first_name or ''} {user.last_name or ''}".strip(),
        internal_role=user.internal_role,
        is_active=user.is_active,
        mfa_enabled=user.mfa_enabled,
        last_login=user.last_login,
        created_at=user.created_at,
    )


@router.post("/{user_id}/reset-password", response_model=MessageResponse)
async def admin_reset_password(
    user_id: UUID,
    body: ChangeUserPasswordRequest,
    current_user: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: force-reset another user's password."""
    from src.infrastructure.database.models import User

    result = await db.execute(select(User).where(User.id == user_id, User.user_type == "internal"))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.password_hash = auth_service.hash_password(body.new_password)
    user.password_changed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()

    logger.info("admin_password_reset", target_user_id=str(user_id), by=str(current_user["user_id"]))
    return MessageResponse(message="Password reset successfully.")
