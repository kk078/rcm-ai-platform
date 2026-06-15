"""API route registration."""

# Core RCM routes
from src.api.routes.auth import router as auth_router
from src.api.routes.claims import router as claims_router
from src.api.routes.coding import router as coding_router
from src.api.routes.denials import router as denials_router
from src.api.routes.payments import router as payments_router
from src.api.routes.patients import router as patients_router
from src.api.routes.payers import router as payers_router
from src.api.routes.analytics import router as analytics_router

# Third-party billing company routes
from src.api.routes.client_management import router as client_mgmt_router
from src.api.routes.charge_intake import router as charge_intake_router
from src.api.routes.provider_portal import router as provider_portal_router
from src.api.routes.work_queue import router as work_queue_router
from src.api.routes.client_billing import router as client_billing_router

# User management
from src.api.routes.users import router as users_router

# Task monitoring
from src.api.routes.tasks import router as tasks_router

# AI Assistant (Ollama/Anthropic-powered chat, batch coding, revenue intelligence)
from src.api.routes.ai_assistant import router as ai_assistant_router

# Admin: feature flags, canary releases, metrics, A/B testing
from src.api.routes.admin import router as admin_router

__all__ = [
    "auth_router",
    "claims_router",
    "coding_router",
    "denials_router",
    "payments_router",
    "patients_router",
    "payers_router",
    "analytics_router",
    "client_mgmt_router",
    "charge_intake_router",
    "provider_portal_router",
    "work_queue_router",
    "client_billing_router",
    "users_router",
    "tasks_router",
    "ai_assistant_router",
    "admin_router",
    "eligibility_router",
    "prior_auth_router",
    "patient_billing_router",
    "documents_router",
    "notifications_router",
    "ehr_router",
    "provider_analytics_router",
]

# Phase 3 — New route modules
from src.api.routes.eligibility import router as eligibility_router
from src.api.routes.prior_auth import router as prior_auth_router
from src.api.routes.patient_billing import router as patient_billing_router
from src.api.routes.documents import router as documents_router
from src.api.routes.notifications import router as notifications_router
from src.api.routes.ehr_integration import router as ehr_router
from src.api.routes.provider_analytics import router as provider_analytics_router
