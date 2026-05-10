"""
Tenant Isolation Middleware — Ensures every request is scoped to the correct practice(s).
This is the core security layer for multi-tenant data isolation.

For provider portal users: locked to their single practice_id
For internal staff: scoped to their assigned practices
For company admins: access to all practices
"""

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import text
import structlog

logger = structlog.get_logger()


class TenantMiddleware(BaseHTTPMiddleware):
    """
    Sets the tenant context for every request based on the authenticated user.
    This context is used by PostgreSQL Row-Level Security to enforce data isolation.
    """

    # Routes that don't require tenant context
    EXEMPT_ROUTES = {"/health", "/ready", "/api/v1/auth/login", "/api/v1/auth/refresh", "/api/docs", "/api/redoc"}

    async def dispatch(self, request: Request, call_next):
        # Skip tenant scoping for exempt routes
        if request.url.path in self.EXEMPT_ROUTES:
            return await call_next(request)

        # Get user info from auth middleware (should run before this)
        user = getattr(request.state, "current_user", None)
        if not user:
            return await call_next(request)  # Auth middleware handles 401

        user_type = user.get("user_type")
        user_id = user.get("user_id")

        if user_type == "provider":
            # Provider portal user: locked to their single practice
            practice_id = user.get("practice_id")
            if not practice_id:
                raise HTTPException(status_code=403, detail="No practice associated with this account")

            request.state.tenant_practice_ids = [practice_id]
            request.state.active_practice_id = practice_id
            request.state.is_single_tenant = True

        elif user_type == "internal":
            internal_role = user.get("internal_role")

            if internal_role in ("company_admin", "qa_reviewer"):
                # Full access — no tenant restriction
                request.state.tenant_practice_ids = None  # None = all practices
                request.state.is_single_tenant = False
            else:
                # Staff: access only assigned practices
                assigned_practices = user.get("assigned_practice_ids", [])
                if not assigned_practices:
                    raise HTTPException(
                        status_code=403,
                        detail="No practices assigned. Contact your manager."
                    )
                request.state.tenant_practice_ids = assigned_practices
                request.state.is_single_tenant = False

            # If a specific practice is selected (client context switching)
            active_practice = request.headers.get("X-Practice-ID")
            if active_practice:
                # Verify user has access to this practice
                if request.state.tenant_practice_ids is not None:
                    if active_practice not in [str(p) for p in request.state.tenant_practice_ids]:
                        raise HTTPException(status_code=403, detail="Access denied to this practice")
                request.state.active_practice_id = active_practice
            else:
                request.state.active_practice_id = None  # Cross-practice context

        logger.debug(
            "tenant_context_set",
            user_id=user_id,
            user_type=user_type,
            active_practice=getattr(request.state, "active_practice_id", None),
        )

        return await call_next(request)


def get_tenant_filter(request: Request) -> dict:
    """
    Helper for route handlers to get the tenant filter for DB queries.

    Returns:
        dict with practice_id for single-practice context,
        or practice_ids list for multi-practice context,
        or empty dict for admin (all practices).
    """
    active = getattr(request.state, "active_practice_id", None)
    if active:
        return {"practice_id": active}

    allowed = getattr(request.state, "tenant_practice_ids", None)
    if allowed is not None:
        return {"practice_id__in": allowed}

    return {}  # Admin: no filter


async def set_rls_context(db_session, request: Request):
    """
    Set PostgreSQL session variables for Row-Level Security.
    Call this at the start of every DB transaction.
    """
    user = getattr(request.state, "current_user", {})
    user_id = user.get("user_id", "")
    user_role = user.get("internal_role", user.get("provider_role", ""))
    practice_id = getattr(request.state, "active_practice_id", "")

    await db_session.execute(text(f"SET LOCAL app.current_user_id = '{user_id}'"))
    await db_session.execute(text(f"SET LOCAL app.user_role = '{user_role}'"))
    if practice_id:
        await db_session.execute(text(f"SET LOCAL app.current_practice_id = '{practice_id}'"))
