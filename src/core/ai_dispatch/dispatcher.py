"""
Dispatch logic — maps RCM queue types to AI agents, enforces the confidence
threshold, and returns a normalised DispatchResult.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .client import CircuitOpenError, call_agent_service
from src.config import get_settings

settings = get_settings()

logger = logging.getLogger(__name__)

# Maps RCM WorkQueueItem.queue_type → agent_type string used by the AI service.
# Aliases (authorization, verification) let callers use either spelling.
QUEUE_TYPE_TO_AGENT: dict[str, str] = {
    "coding":         "coding",
    "billing":        "billing",
    "posting":        "payment_posting",
    "denial":         "ar_denial",
    "follow_up":      "ar_denial",
    "intake":         "patient_intake",   # Fixed: was "coding"
    "prior_auth":     "prior_auth",
    "authorization":  "prior_auth",       # Alias
    "eligibility":    "eligibility",
    "verification":   "eligibility",      # Alias
    "patient_intake": "patient_intake",
}

# Human-readable label for each agent type (used in notes / logs).
AGENT_TYPE_LABEL: dict[str, str] = {
    "coding":          "Medical Coding",
    "billing":         "Claim Billing",
    "payment_posting": "Payment Posting",
    "ar_denial":       "AR / Denial Management",
    "prior_auth":      "Prior Authorization",
    "eligibility":     "Eligibility Verification",
    "patient_intake":  "Patient Intake",
}


@dataclass
class DispatchResult:
    """Normalised outcome of dispatching a work item to an AI agent."""

    success: bool
    confidence: float
    escalate: bool
    agent_type: str
    result: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    error: str = ""
    # Transport / reliability metadata (populated from _meta injected by client.py)
    duration_ms: int = 0
    retry_count: int = 0
    error_code: str = ""
    steps: list = field(default_factory=list)


async def dispatch_item(
    queue_type: str,
    item_data: dict[str, Any],
    threshold_override: float | None = None,
) -> DispatchResult:
    """Route a work item to the appropriate agent and evaluate the response.

    Args:
        queue_type: RCM queue type (coding, billing, posting, denial,
                    follow_up, intake, prior_auth, authorization,
                    eligibility, verification, patient_intake).
        item_data:  Serialised WorkQueueItem fields (enriched with clinical
                    data from related tables by the caller).

    Returns:
        DispatchResult — always returned; never raises.  On transport /
        parsing errors, success=False and escalate=True so the item gets
        assigned to a human.
    """
    agent_type = QUEUE_TYPE_TO_AGENT.get(queue_type)
    if agent_type is None:
        logger.warning(
            "ai_dispatch.dispatcher: unknown queue_type '%s', escalating",
            queue_type,
            extra={"queue_type": queue_type},
        )
        return DispatchResult(
            success=False,
            confidence=0.0,
            escalate=True,
            agent_type="unknown",
            notes=f"No agent mapping for queue_type='{queue_type}'",
        )

    threshold: float = (
        threshold_override if threshold_override is not None
        else getattr(settings, "ai_agent_confidence_threshold", 0.7)
    )

    try:
        raw = await call_agent_service(queue_type, item_data)
    except CircuitOpenError as exc:
        logger.warning(
            "ai_dispatch.dispatcher: circuit open — skipping call for queue_type='%s' agent='%s'",
            queue_type,
            agent_type,
            extra={"queue_type": queue_type, "agent_type": agent_type},
        )
        return DispatchResult(
            success=False,
            confidence=0.0,
            escalate=True,
            agent_type=agent_type,
            notes="AI agent service circuit breaker is open — item escalated for human review.",
            error=str(exc),
            error_code="circuit_open",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "ai_dispatch.dispatcher: transport error for queue_type='%s' agent='%s'",
            queue_type,
            agent_type,
            extra={"queue_type": queue_type, "agent_type": agent_type},
        )
        return DispatchResult(
            success=False,
            confidence=0.0,
            escalate=True,
            agent_type=agent_type,
            notes="Agent service unreachable or returned an error.",
            error=str(exc),
            error_code="transport_error",
        )

    # Extract reliability metadata injected by client.py, then remove it
    # from the raw payload so it doesn't bleed into result.
    meta: dict = raw.pop("_meta", {})
    duration_ms: int = int(meta.get("duration_ms", 0))
    retry_count: int = int(meta.get("retry_count", 0))

    success: bool = bool(raw.get("success", False))
    confidence: float = float(raw.get("confidence", 0.0))
    # Honour the agent's own escalation flag OR apply the confidence threshold.
    agent_wants_escalate: bool = bool(raw.get("escalate", False))
    below_threshold: bool = confidence < threshold
    escalate: bool = agent_wants_escalate or below_threshold or not success

    logger.info(
        "ai_dispatch.dispatcher: item dispatched — queue=%s agent=%s "
        "confidence=%.2f threshold=%.2f escalate=%s retries=%d duration_ms=%d",
        queue_type,
        agent_type,
        confidence,
        threshold,
        escalate,
        retry_count,
        duration_ms,
        extra={
            "queue_type": queue_type,
            "agent_type": agent_type,
            "confidence": confidence,
            "threshold": threshold,
            "escalate": escalate,
            "retry_count": retry_count,
            "duration_ms": duration_ms,
        },
    )

    return DispatchResult(
        success=success,
        confidence=confidence,
        escalate=escalate,
        agent_type=agent_type,
        result=raw.get("result", {}),
        notes=raw.get("notes", ""),
        duration_ms=duration_ms,
        retry_count=retry_count,
        steps=raw.get("steps", []),
    )
