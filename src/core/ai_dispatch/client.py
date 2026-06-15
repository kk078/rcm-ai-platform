"""
HTTP client for the AI Agent service.

Sends work-item payloads to the FastAPI service running in the ai-agents
container (D:\\AIAgents\\api\\main.py) and returns the raw JSON response.

Reliability features
--------------------
* **Exponential-backoff retry** — up to MAX_RETRIES attempts on transient
  transport errors (connect timeout, read timeout, 502/503/504).  Each
  attempt waits 2^(attempt-1) * BASE_DELAY seconds, ±25 % jitter.

* **Circuit breaker** — module-level singleton.  Opens after
  CB_FAILURE_THRESHOLD consecutive failures within CB_WINDOW_SECONDS.
  Stays open for CB_RESET_TIMEOUT_SECONDS, then half-opens to probe.
  When open, calls fail immediately with CircuitOpenError so the caller
  can escalate rather than pile up blocking waits.

Both mechanisms are async-safe and use only stdlib primitives (no
third-party libraries).
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from src.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------

MAX_RETRIES: int = 3          # total attempts (1 original + 2 retries)
BASE_DELAY: float = 1.0       # seconds for attempt 1; doubles each retry
JITTER_FACTOR: float = 0.25   # ±25 % random jitter on each wait

# HTTP status codes considered transient (worth retrying)
_RETRYABLE_STATUS: frozenset[int] = frozenset({429, 500, 502, 503, 504})

# ---------------------------------------------------------------------------
# Circuit breaker configuration
# ---------------------------------------------------------------------------

CB_FAILURE_THRESHOLD: int = 5        # open after this many consecutive failures
CB_WINDOW_SECONDS: float = 60.0      # failure window for threshold counting
CB_RESET_TIMEOUT_SECONDS: float = 60.0  # how long to stay open before half-open probe

# Default timeouts (seconds) — agent calls can be slow due to LLM round-trips.
_CONNECT_TIMEOUT: float = 5.0
_READ_TIMEOUT: float = 120.0


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

class CircuitOpenError(RuntimeError):
    """Raised when the circuit breaker is open and the call is rejected."""


@dataclass
class _CircuitBreaker:
    """Simple three-state circuit breaker (closed → open → half-open)."""

    failure_threshold: int = CB_FAILURE_THRESHOLD
    window_seconds: float = CB_WINDOW_SECONDS
    reset_timeout_seconds: float = CB_RESET_TIMEOUT_SECONDS

    _state: str = field(default="closed", init=False, repr=False)
    _failure_timestamps: list[float] = field(default_factory=list, init=False, repr=False)
    _opened_at: float = field(default=0.0, init=False, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    @property
    def state(self) -> str:
        return self._state

    async def allow(self) -> bool:
        """Return True if the call should proceed; False if the circuit is open."""
        async with self._lock:
            now = time.monotonic()

            if self._state == "closed":
                return True

            if self._state == "open":
                if now - self._opened_at >= self.reset_timeout_seconds:
                    self._state = "half-open"
                    logger.info("ai_dispatch.cb: circuit → half-open (probing)")
                    return True
                return False  # still open

            # half-open: allow one probe
            return True

    async def record_success(self) -> None:
        async with self._lock:
            self._failure_timestamps.clear()
            if self._state != "closed":
                logger.info("ai_dispatch.cb: circuit → closed (probe succeeded)")
            self._state = "closed"

    async def record_failure(self) -> None:
        async with self._lock:
            now = time.monotonic()
            # Evict timestamps outside the window
            self._failure_timestamps = [
                t for t in self._failure_timestamps if now - t <= self.window_seconds
            ]
            self._failure_timestamps.append(now)

            if self._state == "half-open":
                # Probe failed — reopen
                self._state = "open"
                self._opened_at = now
                logger.warning("ai_dispatch.cb: circuit → open (probe failed)")
            elif len(self._failure_timestamps) >= self.failure_threshold:
                self._state = "open"
                self._opened_at = now
                logger.warning(
                    "ai_dispatch.cb: circuit → open "
                    "(%d failures in %.0fs window)",
                    len(self._failure_timestamps),
                    self.window_seconds,
                )


# Module-level singleton — shared across all async calls within a worker process.
_circuit_breaker = _CircuitBreaker()


def get_circuit_breaker() -> _CircuitBreaker:
    """Expose the singleton for testing / monitoring."""
    return _circuit_breaker


# ---------------------------------------------------------------------------
# Internal retry helper
# ---------------------------------------------------------------------------

def _retry_delay(attempt: int) -> float:
    """Compute wait time before *attempt* (1-based).  attempt=1 returns 0."""
    if attempt <= 1:
        return 0.0
    base = BASE_DELAY * (2 ** (attempt - 2))
    jitter = base * JITTER_FACTOR * (2 * random.random() - 1)
    return max(0.0, base + jitter)


def _is_retryable_exception(exc: BaseException) -> bool:
    """True for transient network/HTTP errors worth retrying."""
    if isinstance(exc, (httpx.ConnectError, httpx.TimeoutException)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _RETRYABLE_STATUS
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def call_agent_service(
    queue_type: str,
    item_data: dict[str, Any],
) -> dict[str, Any]:
    """POST to the AI agent service and return the parsed JSON response.

    Args:
        queue_type: RCM queue type string (coding, billing, posting, denial,
                    intake, follow_up, …).
        item_data:  Serialised WorkQueueItem fields forwarded to the agent.

    Returns:
        Dict with keys: success, result, confidence, escalate, agent_type, notes.
        Also includes ``_meta`` with retry_count and duration_ms.

    Raises:
        CircuitOpenError: when the circuit breaker is open.
        httpx.HTTPStatusError: on a non-retryable non-2xx response.
        httpx.TimeoutException / httpx.ConnectError: after all retries
            are exhausted on transport errors.
    """
    if not await _circuit_breaker.allow():
        raise CircuitOpenError(
            f"Circuit breaker is open — ai-agents service unavailable "
            f"(state={_circuit_breaker.state})"
        )

    url = f"{settings.ai_agent_service_url.rstrip('/')}/api/work-items/process"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    api_key: str = getattr(settings, "ai_agent_service_api_key", "")
    if api_key:
        headers["X-API-Key"] = api_key

    payload = {"queue_type": queue_type, "item_data": item_data}
    timeout = httpx.Timeout(
        connect=_CONNECT_TIMEOUT, read=_READ_TIMEOUT, write=10.0, pool=5.0
    )

    start_ns = time.monotonic_ns()
    last_exc: BaseException | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        delay = _retry_delay(attempt)
        if delay > 0:
            logger.info(
                "ai_dispatch.client: retry attempt %d/%d for queue_type='%s' "
                "(waiting %.2fs)",
                attempt, MAX_RETRIES, queue_type, delay,
            )
            await asyncio.sleep(delay)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()

            duration_ms = (time.monotonic_ns() - start_ns) // 1_000_000

            await _circuit_breaker.record_success()

            logger.info(
                "ai_dispatch.client: agent service responded "
                "(queue=%s attempt=%d/%d success=%s confidence=%s duration_ms=%d)",
                queue_type,
                attempt,
                MAX_RETRIES,
                data.get("success"),
                data.get("confidence"),
                duration_ms,
                extra={
                    "queue_type": queue_type,
                    "attempt": attempt,
                    "success": data.get("success"),
                    "confidence": data.get("confidence"),
                    "escalate": data.get("escalate"),
                    "duration_ms": duration_ms,
                },
            )

            # Inject call metadata for caller transparency.
            data["_meta"] = {
                "retry_count": attempt - 1,
                "duration_ms": duration_ms,
                "url": url,
            }
            return data

        except BaseException as exc:  # noqa: BLE001
            last_exc = exc
            duration_ms = (time.monotonic_ns() - start_ns) // 1_000_000

            if not _is_retryable_exception(exc) or attempt == MAX_RETRIES:
                await _circuit_breaker.record_failure()
                logger.error(
                    "ai_dispatch.client: unrecoverable error on attempt %d/%d "
                    "for queue_type='%s' after %dms — %s: %s",
                    attempt, MAX_RETRIES, queue_type, duration_ms,
                    type(exc).__name__, exc,
                    extra={"queue_type": queue_type, "attempt": attempt, "duration_ms": duration_ms},
                )
                raise

            await _circuit_breaker.record_failure()
            logger.warning(
                "ai_dispatch.client: transient error on attempt %d/%d "
                "for queue_type='%s' — %s: %s",
                attempt, MAX_RETRIES, queue_type, type(exc).__name__, exc,
                extra={"queue_type": queue_type, "attempt": attempt},
            )

    # Should be unreachable, but satisfy the type-checker.
    raise RuntimeError("Retry loop exhausted without raising") from last_exc
