"""
Application metrics — Prometheus counters, histograms, gauges.
Exposes /metrics endpoint in FastAPI via prometheus_client.

All metrics use the aethera_ prefix.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from functools import wraps

import structlog

logger = structlog.get_logger()

# Try to import prometheus_client; if not available, use no-op stubs
try:
    from prometheus_client import (
        Counter,
        Gauge,
        Histogram,
        Info,
        generate_latest,
        CONTENT_TYPE_LATEST,
        REGISTRY,
    )
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False
    logger.warning("prometheus_client not installed; metrics disabled")

    # No-op stubs
    class _Noop:
        def labels(self, **_): return self
        def inc(self, *_, **__): pass
        def observe(self, *_, **__): pass
        def set(self, *_, **__): pass
        def info(self, *_, **__): pass

    Counter = Histogram = Gauge = Info = lambda *_, **__: _Noop()
    generate_latest = lambda: b""
    CONTENT_TYPE_LATEST = "text/plain"


# ── Metric definitions ────────────────────────────────────────────────────────

# HTTP
http_requests_total = Counter(
    "aethera_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
)

http_request_duration_seconds = Histogram(
    "aethera_http_request_duration_seconds",
    "HTTP request duration",
    ["method", "endpoint"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

# AI
ai_requests_total = Counter(
    "aethera_ai_requests_total",
    "AI LLM requests",
    ["provider", "operation", "status"],
)

ai_tokens_total = Counter(
    "aethera_ai_tokens_total",
    "Tokens consumed by AI",
    ["provider", "operation"],
)

ai_latency_seconds = Histogram(
    "aethera_ai_latency_seconds",
    "AI response latency",
    ["provider", "operation"],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0],
)

ai_concurrent_gauge = Gauge(
    "aethera_ai_concurrent_requests",
    "Current concurrent AI requests",
)

# Claims
claims_submitted_total = Counter(
    "aethera_claims_submitted_total",
    "Claims submitted",
    ["payer", "status"],
)

denials_total = Counter(
    "aethera_denials_total",
    "Claim denials received",
    ["denial_code", "payer"],
)

appeals_total = Counter(
    "aethera_appeals_total",
    "Appeals filed",
    ["outcome"],
)

collection_rate_gauge = Gauge(
    "aethera_collection_rate",
    "Current collection rate percentage",
    ["practice_id"],
)

# Auth
auth_login_total = Counter(
    "aethera_auth_login_total",
    "Login attempts",
    ["status", "user_type"],
)

auth_failed_total = Counter(
    "aethera_auth_failed_total",
    "Failed auth attempts",
    ["reason"],
)

# Queue
queue_items_gauge = Gauge(
    "aethera_queue_items",
    "Work queue item count",
    ["queue_type", "status"],
)

queue_processing_seconds = Histogram(
    "aethera_queue_processing_seconds",
    "Queue item processing time",
    ["queue_type"],
)

# System
active_users_gauge = Gauge(
    "aethera_active_users",
    "Active authenticated sessions",
)

app_info = Info("aethera_app", "Application information")


def record_request(method: str, endpoint: str, status_code: int, duration: float):
    """Record an HTTP request metric."""
    http_requests_total.labels(
        method=method, endpoint=endpoint, status_code=str(status_code)
    ).inc()
    http_request_duration_seconds.labels(method=method, endpoint=endpoint).observe(duration)


def record_ai_call(provider: str, operation: str, status: str, tokens: int, latency: float):
    """Record an AI service call."""
    ai_requests_total.labels(provider=provider, operation=operation, status=status).inc()
    ai_tokens_total.labels(provider=provider, operation=operation).inc(tokens)
    ai_latency_seconds.labels(provider=provider, operation=operation).observe(latency)


def timed_ai_call(provider: str, operation: str) -> Callable:
    """Decorator to auto-record AI call metrics."""
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            ai_concurrent_gauge.inc()
            start = time.perf_counter()
            status = "success"
            tokens = 0
            try:
                result = await fn(*args, **kwargs)
                if hasattr(result, "tokens_used"):
                    tokens = result.tokens_used
                return result
            except Exception:
                status = "error"
                raise
            finally:
                latency = time.perf_counter() - start
                ai_concurrent_gauge.dec()
                record_ai_call(provider, operation, status, tokens, latency)
        return wrapper
    return decorator
