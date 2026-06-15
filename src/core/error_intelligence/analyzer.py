"""
AI-powered error analysis engine.
Takes a raw error (type, message, traceback, request context) and returns
a structured diagnosis: severity, root cause, suggested fix, and debug steps.
Uses Claude claude-sonnet-4-6 via the Anthropic SDK (already a project dependency).
Falls back gracefully if the API key is not configured.
"""

import json
import structlog
from dataclasses import dataclass, asdict
from typing import Optional

logger = structlog.get_logger()


@dataclass
class ErrorAnalysis:
    severity: str                  # critical | high | medium | low
    root_cause: str                # concise explanation of WHY this happened
    suggested_fix: str             # specific code/config change to resolve it
    affected_area: str             # e.g. "Authentication", "Payment Posting"
    debug_steps: list[str]         # ordered steps to reproduce / investigate
    is_security_related: bool      # flag for immediate escalation
    estimated_impact: str          # e.g. "Affects all users updating profile"
    confidence: str                # high | medium | low — how certain the AI is

    def to_dict(self) -> dict:
        return asdict(self)


_FALLBACK = ErrorAnalysis(
    severity="medium",
    root_cause="AI analysis unavailable — Anthropic API key not configured.",
    suggested_fix="Set ANTHROPIC_API_KEY in your .env file and redeploy.",
    affected_area="Unknown",
    debug_steps=["Review the stack trace manually", "Check application logs"],
    is_security_related=False,
    estimated_impact="Unknown",
    confidence="low",
)


def analyze_error(
    error_type: str,
    message: str,
    stack_trace: str,
    request_path: Optional[str] = None,
    request_method: Optional[str] = None,
    status_code: Optional[int] = None,
    user_id: Optional[str] = None,
    extra_context: Optional[dict] = None,
) -> ErrorAnalysis:
    """
    Synchronous wrapper — calls the Anthropic API and returns a structured analysis.
    Safe to call from Celery tasks (no async required).
    Returns _FALLBACK if the API is unavailable.
    """
    from src.config import get_settings
    settings = get_settings()

    if not settings.anthropic_api_key:
        logger.warning("error_intelligence_skip", reason="no_api_key")
        return _FALLBACK

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        context_parts = []
        if request_path:
            context_parts.append(f"Endpoint: {request_method or 'UNKNOWN'} {request_path}")
        if status_code:
            context_parts.append(f"HTTP Status: {status_code}")
        if user_id:
            context_parts.append(f"User ID: {user_id}")
        if extra_context:
            context_parts.append(f"Additional context: {json.dumps(extra_context, default=str)}")

        context_block = "\n".join(context_parts) if context_parts else "No additional context"

        prompt = f"""You are a senior backend engineer debugging a production error in Aethera AI,
a HIPAA-compliant healthcare Revenue Cycle Management (RCM) platform built with:
- FastAPI + SQLAlchemy + asyncpg (PostgreSQL)
- Celery + Redis for background tasks
- Anthropic Claude for AI features
- JWT authentication with short-lived access tokens

ERROR DETAILS:
Error Type: {error_type}
Message: {message}

Stack Trace:
```
{stack_trace[:3000]}
```

Request Context:
{context_block}

Analyze this error and respond with ONLY a valid JSON object (no markdown, no explanation outside the JSON):
{{
  "severity": "<critical|high|medium|low>",
  "root_cause": "<1-2 sentence explanation of the underlying cause>",
  "suggested_fix": "<specific actionable fix — mention exact file/function/line if identifiable from the stack trace>",
  "affected_area": "<which part of the system: e.g. Authentication, Claim Processing, Payment Posting, AI Engine, Database, etc.>",
  "debug_steps": ["<step 1>", "<step 2>", "<step 3>"],
  "is_security_related": <true|false>,
  "estimated_impact": "<who/what is affected and how broadly>",
  "confidence": "<high|medium|low>"
}}

Severity guide:
- critical: data loss, security breach, complete service outage
- high: feature broken for all users or financial data corrupted
- medium: feature broken for some users or degraded experience
- low: cosmetic, edge case, or minor inconvenience"""

        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw.strip())

        return ErrorAnalysis(
            severity=data.get("severity", "medium"),
            root_cause=data.get("root_cause", "Unknown"),
            suggested_fix=data.get("suggested_fix", "Review stack trace"),
            affected_area=data.get("affected_area", "Unknown"),
            debug_steps=data.get("debug_steps", []),
            is_security_related=bool(data.get("is_security_related", False)),
            estimated_impact=data.get("estimated_impact", "Unknown"),
            confidence=data.get("confidence", "medium"),
        )

    except Exception as e:
        logger.error("error_intelligence_analyzer_failed", error=str(e))
        fallback = ErrorAnalysis(
            severity="medium",
            root_cause=f"AI analysis failed: {str(e)[:200]}",
            suggested_fix="Check the stack trace and application logs manually.",
            affected_area="Unknown",
            debug_steps=["Review stack trace", "Check structlog output"],
            is_security_related=False,
            estimated_impact="Unknown",
            confidence="low",
        )
        return fallback
