"""
FastAPI dependencies for authentication and authorization.

- get_current_user: Extracts and validates the JWT from the Authorization header
- require_role: Factory that creates role-checking dependencies
- require_practice_access: Checks that the user has access to a practice
"""

from functools import wraps
from uuid import UUID

import structlog
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.auth.jwt_handler import AuthenticationError, decode_token
from src.infrastructure.auth.schemas import TokenData
from src.infrastructure.auth.token_blacklist import token_blacklist
from src.infrastructure.database.session import get_db

logger = structlog.get_logger()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

# Internal roles that get full access (no tenant filter)
ADMIN_ROLES = {"company_admin", "qa_reviewer"}


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Validate the access token and return a user info dict.

    Sets request.state.current_user for downstream middleware.
    Raises 401 if token is invalid, expired, or blacklisted.
    Raises 403 if user account is inactive.
    """
    try:
        payload = decode_token(token)
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )

    jti = payload.get("jti")
    if jti and await token_blacklist.is_blacklisted(jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    # Lazy import to avoid circular dependency with models
    from src.infrastructure.database.models import User

    # Load user from DB to check active status
    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    user_info = {
        "user_id": user.id,
        "email": user.email,
        "user_type": user.user_type,
        "internal_role": user.internal_role,
        "provider_role": user.provider_role,
        "practice_id": user.practice_id,
        "assigned_practice_ids": [a.practice_id for a in user.staff_assignments] if user.staff_assignments else [],
    }

    logger.debug("authenticated_user", user_id=str(user.id), user_type=user.user_type)
    return user_info


def require_role(*allowed_roles: str):
    """
    Dependency factory that checks if the current user has one of the allowed roles.

    For internal users: checks internal_role
    For provider users: checks provider_role

    Usage:
        @router.get("/admin", dependencies=[Depends(require_role("company_admin"))])
    """
    async def role_checker(current_user: dict = Depends(get_current_user)) -> dict:
        user_type = current_user.get("user_type")
        user_role = current_user.get("internal_role") if user_type == "internal" else current_user.get("provider_role")

        if not user_role or user_role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user_role}' not authorized. Required: {', '.join(allowed_roles)}",
            )
        return current_user

    return role_checker


def require_practice_access(practice_id_param: str = "practice_id"):
    """
    Dependency factory that checks if the current user has access to the practice
    specified in the path/query parameter.

    - Admin roles (company_admin, qa_reviewer) have access to all practices.
    - Internal staff can only access their assigned practices.
    - Provider users can only access their own practice.

    Usage:
        @router.get("/{practice_id}/claims", dependencies=[Depends(require_practice_access())])
    """
    async def practice_checker(
        request: Request,
        current_user: dict = Depends(get_current_user),
    ) -> dict:
        user_type = current_user.get("user_type")
        user_role = current_user.get("internal_role")

        # Admin roles have full access
        if user_type == "internal" and user_role in ADMIN_ROLES:
            return current_user

        # Extract practice_id from path params, query params, or request body
        practice_id = request.path_params.get(practice_id_param)
        if not practice_id:
            practice_id = request.query_params.get(practice_id_param)
        if not practice_id:
            # Try JSON body
            try:
                body = await request.json()
                practice_id = body.get(practice_id_param)
            except Exception:
                pass

        if not practice_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Practice ID not found in request",
            )

        practice_id = UUID(str(practice_id))
        allowed_practices = current_user.get("assigned_practice_ids", [])

        if user_type == "provider":
            user_practice = current_user.get("practice_id")
            if practice_id != user_practice:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied to this practice",
                )
        elif user_type == "internal":
            if practice_id not in allowed_practices:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied to this practice",
                )

        return current_user

    return practice_checker