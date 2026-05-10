"""
Row-Level Security context management for PostgreSQL.

Sets session variables that RLS policies use to filter rows by tenant.
Uses PostgreSQL's set_config() function with parameterized queries
to prevent SQL injection.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import structlog

logger = structlog.get_logger()

# Valid internal roles (billing company staff)
INTERNAL_ROLES = {
    "company_admin",
    "billing_manager",
    "coder",
    "payment_poster",
    "denial_analyst",
    "qa_reviewer",
    "readonly",
}

# Valid provider roles (practice portal users)
PROVIDER_ROLES = {
    "practice_admin",
    "provider",
    "office_manager",
    "front_desk",
}

ALL_VALID_ROLES = INTERNAL_ROLES | PROVIDER_ROLES

# Allowlisted session variable names (prevents injection via variable name)
ALLOWED_VARS = {"app.current_user_id", "app.user_role", "app.current_practice_id"}


async def set_tenant_context(
    session: AsyncSession,
    user_id: UUID | str,
    user_role: str,
    practice_id: UUID | str | None = None,
) -> None:
    """
    Set PostgreSQL session variables for Row-Level Security.

    Uses set_config(var, value, true) which is equivalent to SET LOCAL
    but accepts parameterized values via SQLAlchemy's text() binding.
    The 'true' parameter makes the setting transaction-local (reset on
    commit/rollback), matching SET LOCAL behavior.

    Args:
        session: Active async database session.
        user_id: UUID of the authenticated user.
        user_role: The user's role (internal_role or provider_role).
        practice_id: UUID of the active practice (required for provider users).
    """
    # Validate and normalize inputs
    if isinstance(user_id, str):
        user_id = UUID(user_id)  # Raises ValueError if invalid format

    user_role = str(user_role).strip()[:30]

    # Set user ID and role using set_config for safe parameterized queries
    await session.execute(
        text("SELECT set_config(:var, :value, true)"),
        {"var": "app.current_user_id", "value": str(user_id)},
    )
    await session.execute(
        text("SELECT set_config(:var, :value, true)"),
        {"var": "app.user_role", "value": user_role},
    )

    if practice_id is not None:
        if isinstance(practice_id, str):
            practice_id = UUID(practice_id)
        await session.execute(
            text("SELECT set_config(:var, :value, true)"),
            {"var": "app.current_practice_id", "value": str(practice_id)},
        )
    else:
        # Clear practice context for cross-practice access (admin/manager)
        await session.execute(
            text("SELECT set_config(:var, :value, true)"),
            {"var": "app.current_practice_id", "value": ""},
        )

    logger.debug(
        "rls_context_set",
        user_id=str(user_id),
        user_role=user_role,
        practice_id=str(practice_id) if practice_id else None,
    )