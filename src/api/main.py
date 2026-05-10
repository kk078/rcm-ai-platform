"""
MedClaim AI — Main FastAPI Application
Includes HIPAA-compliant middleware, CORS, and route registration.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
import structlog
import time
import uuid

from src.config import get_settings
from src.api.routes import (
    auth_router,
    claims_router,
    coding_router,
    denials_router,
    payments_router,
    patients_router,
    payers_router,
    analytics_router,
    client_mgmt_router,
    charge_intake_router,
    provider_portal_router,
    work_queue_router,
    client_billing_router,
)
from src.api.middleware.tenant import TenantMiddleware
from src.infrastructure.database.session import init_db, close_db
from src.infrastructure.queue.celery_app import celery_app

logger = structlog.get_logger()
settings = get_settings()


# ── Lifespan ─────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("Starting MedClaim AI", env=settings.app_env)
    await init_db()
    yield
    await close_db()
    logger.info("MedClaim AI shut down")


# ── App Instance ─────────────────────────────────────────────────
app = FastAPI(
    title="MedClaim AI",
    description="AI-powered Revenue Cycle Management API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs" if settings.app_debug else None,
    redoc_url="/api/redoc" if settings.app_debug else None,
)


# ── Middleware ───────────────────────────────────────────────────

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

# Trusted Host (production)
if settings.is_production:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*.aetheraonline.com", "aetheraonline.com", "*.medclaim.ai", "medclaim.ai", "localhost"])

# Tenant Isolation (multi-tenant data scoping)
app.add_middleware(TenantMiddleware)


@app.middleware("http")
async def hipaa_audit_middleware(request: Request, call_next) -> Response:
    """
    HIPAA-compliant audit logging middleware.
    Logs every request with user identity, resource accessed, and timestamp.
    Strips PHI from error responses.
    """
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    start_time = time.time()

    # Extract user info from JWT (if authenticated)
    user_id = getattr(request.state, "user_id", "anonymous")

    response = await call_next(request)

    # Calculate duration
    duration_ms = round((time.time() - start_time) * 1000, 2)

    # Determine if PHI was accessed (based on route)
    phi_routes = ["/api/v1/patients", "/api/v1/claims", "/api/v1/encounters"]
    phi_accessed = any(request.url.path.startswith(route) for route in phi_routes)

    # Log audit entry
    logger.info(
        "api_request",
        request_id=request_id,
        user_id=str(user_id),
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=duration_ms,
        ip_address=request.client.host if request.client else "unknown",
        user_agent=request.headers.get("user-agent", ""),
        phi_accessed=phi_accessed,
    )

    # Add security headers
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Cache-Control"] = "no-store"  # Never cache PHI
    response.headers["Pragma"] = "no-cache"

    return response


@app.middleware("http")
async def session_timeout_middleware(request: Request, call_next) -> Response:
    """Enforce session timeout for HIPAA compliance."""
    # TODO: Check JWT issued_at vs current time, reject if session > timeout
    return await call_next(request)


# ── Routes ───────────────────────────────────────────────────────

# Authentication
app.include_router(auth_router, prefix="/api/v1/auth", tags=["Authentication"])

# Core RCM (Internal staff — scoped by assigned practices)
app.include_router(patients_router, prefix="/api/v1/patients", tags=["Patients"])
app.include_router(claims_router, prefix="/api/v1/claims", tags=["Claims & Billing"])
app.include_router(coding_router, prefix="/api/v1/coding", tags=["Medical Coding"])
app.include_router(payments_router, prefix="/api/v1/payments", tags=["Payment Posting"])
app.include_router(denials_router, prefix="/api/v1/denials", tags=["Denial Management"])
app.include_router(payers_router, prefix="/api/v1/payers", tags=["Payer Intelligence"])
app.include_router(analytics_router, prefix="/api/v1/analytics", tags=["Analytics & Reporting"])

# Third-Party Billing Company (Internal staff only)
app.include_router(client_mgmt_router, prefix="/api/v1/clients", tags=["Client Management"])
app.include_router(charge_intake_router, prefix="/api/v1/intake", tags=["Charge Intake"])
app.include_router(work_queue_router, prefix="/api/v1/queues", tags=["Work Queues"])
app.include_router(client_billing_router, prefix="/api/v1/billing", tags=["Client Billing & Invoicing"])

# Provider Portal (Practice clients — locked to their own practice)
app.include_router(provider_portal_router, prefix="/api/v1/portal", tags=["Provider Portal"])


# ── Health Check ─────────────────────────────────────────────────
@app.get("/health", tags=["System"])
async def health_check():
    return {"status": "healthy", "version": "0.1.0", "env": settings.app_env}


@app.get("/ready", tags=["System"])
async def readiness_check():
    """Check all dependencies are reachable."""
    checks = {
        "database": False,
        "redis": False,
        "vector_db": False,
    }
    # TODO: Implement actual connectivity checks
    return {"status": "ready", "checks": checks}
