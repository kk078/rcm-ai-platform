"""
Provider user management routes — admin-only CRUD for provider portal accounts.
Creates logins for practices, physicians, and hospitals so they can access the provider portal.
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
from src.infrastructure.auth.middleware import get_current_user
from src.infrastructure.auth.service import AuthService
from src.infrastructure.database.session import get_db

logger = structlog.get_logger()
auth_service = AuthService()
router = APIRouter()

PROVIDER_ROLES = [
    "practice_admin",
    "physician",
    "office_manager",
    "billing_contact",
    "read_only",
]


# ── Schemas ──────────────────────────────────────────────────────────────

class PracticeOut(BaseModel):
    id: UUID
    practice_name: str
    specialty_primary: Optional[str] = None
    status: str

    model_config = {"from_attributes": True}


class ProviderUserOut(BaseModel):
    id: UUID
    email: str
    first_name: str
    last_name: str
    full_name: str
    provider_role: Optional[str]
    practice_id: Optional[UUID]
    practice_name: Optional[str]
    is_active: bool
    must_change_password: bool
    last_login: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class CreateProviderUserRequest(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    provider_role: str
    practice_id: Optional[UUID] = None
    password: str
    must_change_password: bool = True

    @field_validator("provider_role")
    @classmethod
    def valid_role(cls, v: str) -> str:
        if v not in PROVIDER_ROLES:
            raise ValueError(f"Role must be one of: {', '.join(PROVIDER_ROLES)}")
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


class UpdateProviderUserRequest(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    provider_role: Optional[str] = None
    practice_id: Optional[UUID] = None
    is_active: Optional[bool] = None

    @field_validator("provider_role")
    @classmethod
    def valid_role(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in PROVIDER_ROLES:
            raise ValueError(f"Role must be one of: {', '.join(PROVIDER_ROLES)}")
        return v


class ResetProviderPasswordRequest(BaseModel):
    new_password: str
    must_change_password: bool = True

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


# ── Helper ────────────────────────────────────────────────────────────────

def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("internal_role") != "company_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only company administrators can manage provider logins",
        )
    return current_user


async def _enrich(user, db: AsyncSession) -> ProviderUserOut:
    """Attach practice_name to a user row."""
    practice_name = None
    if user.practice_id:
        from src.infrastructure.database.models import Practice
        p = await db.get(Practice, user.practice_id)
        if p:
            practice_name = p.practice_name
    return ProviderUserOut(
        id=user.id,
        email=user.email,
        first_name=user.first_name or "",
        last_name=user.last_name or "",
        full_name=f"{user.first_name or ''} {user.last_name or ''}".strip(),
        provider_role=user.provider_role,
        practice_id=user.practice_id,
        practice_name=practice_name,
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        last_login=user.last_login,
        created_at=user.created_at,
    )


# ── Practices list (for dropdown) ─────────────────────────────────────────

@router.get("/practices", response_model=list[PracticeOut])
async def list_practices(
    current_user: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all active practices for the create-user dropdown."""
    from src.infrastructure.database.models import Practice
    result = await db.execute(
        select(Practice)
        .where(Practice.status != "terminated")
        .order_by(Practice.practice_name)
    )
    return result.scalars().all()


# ── Provider user CRUD ────────────────────────────────────────────────────

@router.get("", response_model=list[ProviderUserOut])
async def list_provider_users(
    current_user: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all provider portal user accounts."""
    from src.infrastructure.database.models import User
    result = await db.execute(
        select(User)
        .where(User.user_type == "provider")
        .order_by(User.created_at.desc())
    )
    users = result.scalars().all()
    return [await _enrich(u, db) for u in users]


@router.post("", response_model=ProviderUserOut, status_code=status.HTTP_201_CREATED)
async def create_provider_user(
    body: CreateProviderUserRequest,
    current_user: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Create a new provider portal login for a practice, physician, or hospital."""
    from src.infrastructure.database.models import User, Practice

    # Check email uniqueness
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )

    # Validate practice exists if provided
    if body.practice_id:
        practice = await db.get(Practice, body.practice_id)
        if not practice:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Practice not found")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    user = User(
        email=body.email,
        password_hash=auth_service.hash_password(body.password),
        first_name=body.first_name.strip(),
        last_name=body.last_name.strip(),
        user_type="provider",
        provider_role=body.provider_role,
        practice_id=body.practice_id,
        is_active=True,
        mfa_enabled=False,
        must_change_password=body.must_change_password,
        password_changed_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    logger.info(
        "provider_user_created",
        new_user_id=str(user.id),
        email=user.email,
        role=user.provider_role,
        by=str(current_user["user_id"]),
    )
    return await _enrich(user, db)


@router.patch("/{user_id}", response_model=ProviderUserOut)
async def update_provider_user(
    user_id: UUID,
    body: UpdateProviderUserRequest,
    current_user: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Update a provider user's details or active status."""
    from src.infrastructure.database.models import User, Practice

    result = await db.execute(
        select(User).where(User.id == user_id, User.user_type == "provider")
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider user not found")

    if body.practice_id is not None:
        if body.practice_id:
            practice = await db.get(Practice, body.practice_id)
            if not practice:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Practice not found")
        user.practice_id = body.practice_id

    if body.first_name is not None:
        user.first_name = body.first_name.strip()
    if body.last_name is not None:
        user.last_name = body.last_name.strip()
    if body.provider_role is not None:
        user.provider_role = body.provider_role
    if body.is_active is not None:
        user.is_active = body.is_active

    user.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()
    await db.refresh(user)

    logger.info("provider_user_updated", target_user_id=str(user_id), by=str(current_user["user_id"]))
    return await _enrich(user, db)


@router.post("/{user_id}/reset-password", response_model=MessageResponse)
async def reset_provider_password(
    user_id: UUID,
    body: ResetProviderPasswordRequest,
    current_user: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin: force-reset a provider user's password."""
    from src.infrastructure.database.models import User

    result = await db.execute(
        select(User).where(User.id == user_id, User.user_type == "provider")
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider user not found")

    user.password_hash = auth_service.hash_password(body.new_password)
    user.password_changed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    user.must_change_password = body.must_change_password
    await db.commit()

    logger.info("provider_password_reset", target_user_id=str(user_id), by=str(current_user["user_id"]))
    return MessageResponse(message="Password reset successfully.")


@router.get("/roles", response_model=list[str])
async def list_provider_roles(
    current_user: dict = Depends(require_admin),
):
    """Return the list of valid provider portal roles."""
    return PROVIDER_ROLES
