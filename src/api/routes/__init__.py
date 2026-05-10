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

__all__ = [
    # Core
    "auth_router",
    "claims_router",
    "coding_router",
    "denials_router",
    "payments_router",
    "patients_router",
    "payers_router",
    "analytics_router",
    # Third-Party Billing
    "client_mgmt_router",
    "charge_intake_router",
    "provider_portal_router",
    "work_queue_router",
    "client_billing_router",
]
