"""Role-based access control: super-admin gate + agent-area scoping.

Tiers:
  - SUPER ADMIN  = internal user with internal_role == "company_admin". Full app config:
    user management, advanced AI assistant (agent control plane, directives), and
    knowledge-base management (adding/removing reference sources).
  - STAFF        = other internal users. Basic AI assistant (coding/billing/denials/auth
    Q&A, reference-grounded) and the agent queues for their assigned areas.

Agent areas align to the dispatchable agent/queue types. A user's areas come from their
internal_role plus any StaffAssignment.role_in_practice rows; super admins get all areas.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status

from src.infrastructure.auth.middleware import get_current_user

# Canonical agent areas (mirror the dispatch queue/agent types).
AGENT_AREAS: tuple[str, ...] = (
    "coding", "billing", "denials", "prior_auth", "eligibility",
    "payment_posting", "charge_capture", "patient_intake", "claim_status", "credentialing",
)
_ALL = set(AGENT_AREAS)

# Map a role (internal_role or StaffAssignment.role_in_practice) -> agent areas.
ROLE_AREAS: dict[str, set[str]] = {
    # super admin / managers see everything
    "company_admin": set(_ALL),
    "billing_manager": set(_ALL),
    "manager": set(_ALL),
    "qa_reviewer": set(_ALL),
    # specialists
    "coder": {"coding", "charge_capture"},
    "billing_specialist": {"billing", "payment_posting", "claim_status", "prior_auth", "eligibility"},
    "biller": {"billing", "payment_posting", "claim_status"},
    "ar_specialist": {"denials", "claim_status", "billing"},
    "payment_poster": {"payment_posting"},
    "poster": {"payment_posting"},
    "denial_manager": {"denials", "claim_status"},
    "denial_analyst": {"denials"},
    "denials_specialist": {"denials"},
    "prior_auth_specialist": {"prior_auth"},
    "auth_specialist": {"prior_auth"},
    "eligibility_specialist": {"eligibility"},
    "intake_specialist": {"patient_intake", "eligibility"},
    "credentialing_specialist": {"credentialing"},
    "viewer": set(),
}

SUPER_ADMIN_ROLE = "company_admin"


def is_super_admin(user: dict) -> bool:
    return (user or {}).get("user_type") == "internal" and (user or {}).get("internal_role") == SUPER_ADMIN_ROLE


def user_agent_areas(user: dict, assignment_roles: list[str] | None = None) -> set[str]:
    """Agent areas a user may work. Super admins get all; otherwise union of their
    internal_role areas and any StaffAssignment role areas."""
    if is_super_admin(user):
        return set(_ALL)
    areas: set[str] = set()
    role = (user or {}).get("internal_role")
    if role and role in ROLE_AREAS:
        areas |= ROLE_AREAS[role]
    for r in (assignment_roles or []):
        areas |= ROLE_AREAS.get(r, set())
    return areas


def can_access_area(user: dict, area: str, assignment_roles: list[str] | None = None) -> bool:
    return is_super_admin(user) or area in user_agent_areas(user, assignment_roles)


def require_super_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """FastAPI dependency — 403 unless the caller is a super admin (company_admin)."""
    if not is_super_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin access required for this feature.",
        )
    return current_user
