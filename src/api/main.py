"""
Aethera AI — Main FastAPI Application
HIPAA-compliant middleware, CORS, rate limiting, and route registration.
Supports 50+ concurrent users via async I/O and connection pooling.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
import structlog
import time
import uuid
import redis.asyncio as aioredis

from src.config import get_settings
from src.api.routes.error_intelligence import router as error_intelligence_router
from src.api.routes.provider_users import router as provider_users_router
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
    users_router,
    tasks_router,
    ai_assistant_router,
    admin_router,
)
from src.api.routes.eligibility import router as eligibility_router
from src.api.routes.prior_auth import router as prior_auth_router
from src.api.routes.claim_forms import router as claim_forms_router
from src.api.routes.patient_billing import router as patient_billing_router
from src.api.routes.documents import router as documents_router
from src.api.routes.notifications import router as notifications_router
from src.api.routes.ehr_integration import router as ehr_router
from src.api.routes.provider_analytics import router as provider_analytics_router
from src.api.middleware.tenant import TenantMiddleware
from src.infrastructure.database.session import init_db, close_db
from src.infrastructure.queue.celery_app import celery_app

logger = structlog.get_logger()
settings = get_settings()

# ── Sentry before_send hook (defined first — used in init below) ──────────
def _sentry_before_send(event, hint):
    """Strips PHI fields from request bodies before sending to Sentry (HIPAA)."""
    phi_fields = {"password", "password_hash", "ssn", "dob", "date_of_birth", "tin", "credit_card"}
    if "request" in event:
        req_data = event["request"].get("data", {})
        if isinstance(req_data, dict):
            for field in phi_fields:
                if field in req_data:
                    req_data[field] = "[REDACTED]"
    return event


# ── Sentry Initialization ─────────────────────────────────────
if settings.sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
    from sentry_sdk.integrations.redis import RedisIntegration

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.app_env,
        release="aethera-ai@1.0.0",
        traces_sample_rate=0.2,
        profiles_sample_rate=0.1,
        send_default_pii=False,          # HIPAA: never send PII to Sentry
        integrations=[
            StarletteIntegration(transaction_style="endpoint"),
            FastApiIntegration(transaction_style="endpoint"),
            CeleryIntegration(monitor_beat_tasks=True),
            SqlalchemyIntegration(),
            RedisIntegration(),
        ],
        before_send=_sentry_before_send,
    )
    logger.info("sentry_initialized", environment=settings.app_env)
else:
    logger.warning("sentry_disabled", reason="SENTRY_DSN not configured")


# ── Rate Limiter ─────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit_default])


# ── Lifespan ─────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("Starting Aethera AI", env=settings.app_env, version="1.0.0")
    await init_db()
    yield
    await close_db()
    logger.info("Aethera AI shut down cleanly")


# ── App Instance ─────────────────────────────────────────────
app = FastAPI(
    title="Aethera AI",
    description="AI-powered Revenue Cycle Management — by Aethera Healthcare",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# Attach rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── Middleware ───────────────────────────────────────────────

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

# Rate limiting
app.add_middleware(SlowAPIMiddleware)

# Trusted Host (production)
if settings.is_production:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[
            "*.aetherahealthcare.com",
            "aetherahealthcare.com",
            "rcm.aetherahealthcare.com",
            "localhost",
        ],
    )

# Tenant Isolation (multi-tenant data scoping)
app.add_middleware(TenantMiddleware)


# ── Global Error Handlers ─────────────────────────────────────
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Convert FastAPI validation errors into clean human-readable strings."""
    errors = exc.errors()
    messages = []
    for error in errors:
        field = " → ".join(str(loc) for loc in error["loc"] if str(loc) != "body")
        messages.append(f"{field}: {error['msg']}" if field else error["msg"])
    return JSONResponse(
        status_code=422,
        content={"detail": "; ".join(messages), "request_id": getattr(request.state, "request_id", "")},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Ensure all HTTP exceptions return clean JSON."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc.detail), "request_id": getattr(request.state, "request_id", "")},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all — prevent unhandled exceptions from leaking stack traces.
    Also captures the error for AI analysis via the Error Intelligence pipeline."""
    import traceback
    tb = traceback.format_exc()
    logger.error("unhandled_error", error=str(exc), traceback=tb)

    # Capture Sentry event ID (if Sentry is configured)
    sentry_event_id = None
    try:
        if settings.sentry_dsn:
            import sentry_sdk
            sentry_event_id = sentry_sdk.last_event_id()
    except Exception:
        pass

    # Fire AI error analysis (non-blocking)
    try:
        from src.core.error_intelligence.capture import capture_error
        capture_error(exc, request=request, status_code=500, sentry_event_id=sentry_event_id)
    except Exception:
        pass

    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Please try again.", "request_id": getattr(request.state, "request_id", "")},
    )


# ── HIPAA Audit + Security Headers ──────────────────────────
@app.middleware("http")
async def hipaa_audit_middleware(request: Request, call_next) -> Response:
    """
    HIPAA-compliant audit logging on every request.
    Logs: user identity, resource, IP, duration, PHI access flag.
    Adds comprehensive security headers on every response.
    """
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    start_time = time.time()

    user_id = getattr(request.state, "user_id", "anonymous")
    response = await call_next(request)
    duration_ms = round((time.time() - start_time) * 1000, 2)

    phi_routes = ["/api/v1/patients", "/api/v1/claims", "/api/v1/encounters"]
    phi_accessed = any(request.url.path.startswith(r) for r in phi_routes)

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

    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none';"
    )

    # Record Prometheus metrics (fire-and-forget, never fail a request)
    try:
        from src.core.observability.metrics import record_request
        record_request(
            method=request.method,
            endpoint=request.url.path,
            status_code=response.status_code,
            duration=(time.time() - start_time),
        )
    except Exception:
        pass

    return response


# ── HIPAA Session Timeout ────────────────────────────────────
@app.middleware("http")
async def session_timeout_middleware(request: Request, call_next) -> Response:
    """
    Enforce HIPAA idle session timeout (default 15 minutes).
    Rejects authenticated requests whose JWT iat is older than session_timeout_minutes
    unless the path is explicitly exempt.
    """
    exempt_prefixes = (
        "/api/v1/auth/",
        "/health",
        "/ready",
        "/api/docs",
        "/api/redoc",
        "/openapi.json",
    )
    if any(request.url.path.startswith(p) for p in exempt_prefixes):
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        try:
            import jwt as pyjwt
            payload = pyjwt.decode(token, options={"verify_signature": False})
            issued_at = payload.get("iat", 0)
            timeout_secs = settings.session_timeout_minutes * 60
            if time.time() - issued_at > timeout_secs:
                return JSONResponse(
                    status_code=401,
                    content={
                        "detail": "Session expired due to inactivity. Please log in again.",
                        "code": "SESSION_TIMEOUT",
                    },
                )
        except Exception:
            pass  # Malformed token handled by downstream auth middleware

    return await call_next(request)


# ── Routes ───────────────────────────────────────────────────

# Authentication
app.include_router(auth_router, prefix="/api/v1/auth", tags=["Authentication"])

# Core RCM
app.include_router(patients_router, prefix="/api/v1/patients", tags=["Patients"])
app.include_router(claims_router, prefix="/api/v1/claims", tags=["Claims & Billing"])
app.include_router(coding_router, prefix="/api/v1/coding", tags=["Medical Coding"])
app.include_router(payments_router, prefix="/api/v1/payments", tags=["Payment Posting"])
app.include_router(denials_router, prefix="/api/v1/denials", tags=["Denial Management"])
app.include_router(payers_router, prefix="/api/v1/payers", tags=["Payer Intelligence"])
app.include_router(analytics_router, prefix="/api/v1/analytics", tags=["Analytics & Reporting"])

# Third-Party Billing Company
app.include_router(client_mgmt_router, prefix="/api/v1/clients", tags=["Client Management"])
app.include_router(charge_intake_router, prefix="/api/v1/intake", tags=["Charge Intake"])
app.include_router(work_queue_router, prefix="/api/v1/queues", tags=["Work Queues"])
app.include_router(client_billing_router, prefix="/api/v1/billing", tags=["Client Billing & Invoicing"])

# Provider Portal
app.include_router(provider_portal_router, prefix="/api/v1/portal", tags=["Provider Portal"])

# Task Monitoring
app.include_router(users_router, prefix="/api/v1/users", tags=["User Management"])

# Task Monitoring
app.include_router(tasks_router, prefix="/api/v1/tasks", tags=["Task Monitoring"])
app.include_router(ai_assistant_router, prefix="/api/v1/ai", tags=["AI Assistant"])
app.include_router(admin_router, prefix="/api/v1/admin", tags=["Admin & Observability"])

# Phase 3 — New modules (routers self-declare their sub-prefix; mount at /api/v1)
app.include_router(eligibility_router, prefix="/api/v1")
app.include_router(prior_auth_router, prefix="/api/v1")
app.include_router(patient_billing_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")
app.include_router(notifications_router, prefix="/api/v1")
app.include_router(ehr_router, prefix="/api/v1")
app.include_router(provider_analytics_router, prefix="/api/v1")

# Error Intelligence (AI auto-debugging dashboard)
app.include_router(error_intelligence_router, prefix="/api/v1/errors", tags=["Error Intelligence"])
app.include_router(provider_users_router, prefix="/api/v1/provider-users", tags=["Provider User Management"])
app.include_router(claim_forms_router, prefix="/api/v1/claim-forms", tags=["Claim Forms"])


# ── Health & Readiness ───────────────────────────────────────
@app.get("/health", tags=["System"])
async def health_check():
    """Lightweight liveness probe — always fast."""
    return {
        "status": "healthy",
        "app": "Aethera AI",
        "version": "1.0.0",
        "env": settings.app_env,
    }


@app.get("/ready", tags=["System"])
async def readiness_check():
    """Deep readiness probe — checks all critical dependencies."""
    import sqlalchemy
    checks: dict[str, bool] = {}
    overall = True

    # Database
    try:
        from src.infrastructure.database.session import get_engine
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(sqlalchemy.text("SELECT 1"))
        checks["database"] = True
    except Exception as e:
        logger.warning("readiness_db_fail", error=str(e))
        checks["database"] = False
        overall = False

    # Redis
    try:
        r = aioredis.from_url(settings.redis_url, socket_connect_timeout=2)
        await r.ping()
        await r.aclose()
        checks["redis"] = True
    except Exception as e:
        logger.warning("readiness_redis_fail", error=str(e))
        checks["redis"] = False
        overall = False

    # Qdrant (non-fatal — AI degrades gracefully)
    try:
        from qdrant_client import AsyncQdrantClient
        qclient = AsyncQdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key or None,
            timeout=3,
        )
        await qclient.get_collections()
        await qclient.close()
        checks["vector_db"] = True
    except Exception as e:
        logger.warning("readiness_vector_db_fail", error=str(e))
        checks["vector_db"] = False  # non-fatal: vector DB optional, AI degrades gracefully

    status_code = 200 if overall else 503
    return JSONResponse(
        status_code=status_code,
        content={"status": "ready" if overall else "not_ready", "checks": checks},
    )