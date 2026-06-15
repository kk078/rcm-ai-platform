"""
AI Assistant routes — RCM chatbot, batch coding, revenue intelligence.
All endpoints use Anthropic Claude with semaphore-controlled concurrency.
"""

from __future__ import annotations

import json
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.auth.middleware import get_current_user
from src.infrastructure.database.session import get_db

logger = structlog.get_logger()
router = APIRouter()


# ── Request / Response Models ────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    context: str | None = None
    stream: bool = False


class ChatResponse(BaseModel):
    message: str
    session_id: str
    tokens_used: int = 0


class BatchCodingCase(BaseModel):
    case_id: str
    clinical_text: str
    encounter_type: str | None = None
    place_of_service: str | None = None
    patient_age: int | None = None
    patient_gender: str | None = None


class BatchCodingRequest(BaseModel):
    cases: list[BatchCodingCase] = Field(..., max_length=50)


class BatchCodingResult(BaseModel):
    case_id: str
    success: bool
    diagnoses: list[dict] = Field(default_factory=list)
    procedures: list[dict] = Field(default_factory=list)
    reasoning: str = ""
    error: str | None = None


class BatchCodingResponse(BaseModel):
    results: list[BatchCodingResult]
    total: int
    succeeded: int
    failed: int


class RevenueInsightRequest(BaseModel):
    analytics_data: dict
    practice_id: UUID | None = None


# ── AI Chat Assistant ────────────────────────────────────────────────────────

@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    RCM AI assistant — answers billing, coding, and compliance questions.
    Supports multi-turn conversation. Set stream=true for streaming response.
    """
    from src.core.nlp.ai_service import get_ai_service
    ai = get_ai_service()

    messages = [{"role": m.role, "content": m.content} for m in body.messages]

    if body.stream:
        async def _event_stream():
            try:
                gen = await ai.chat(messages=messages, context=body.context, stream=True)
                async for chunk in gen:
                    # SSE format
                    yield f"data: {json.dumps({'delta': chunk})}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                logger.error("chat_stream_error", error=str(e))
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

        return StreamingResponse(
            _event_stream(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    try:
        response = await ai.chat(messages=messages, context=body.context, stream=False)
        return ChatResponse(
            message=response.message,
            session_id=response.session_id,
            tokens_used=response.tokens_used,
        )
    except Exception as e:
        logger.error("chat_error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI assistant is temporarily unavailable.",
        )


# ── Batch Medical Coding ─────────────────────────────────────────────────────

@router.post("/coding/batch", response_model=BatchCodingResponse)
async def batch_coding(
    body: BatchCodingRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Process up to 50 clinical cases concurrently with AI medical coding.
    Returns coded results for each case. Failed cases include error details.
    """
    from src.core.nlp.ai_service import get_ai_service
    ai = get_ai_service()

    if not body.cases:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No cases provided.")

    cases = [
        {
            "clinical_text": c.clinical_text,
            "encounter_type": c.encounter_type,
            "place_of_service": c.place_of_service,
            "patient_age": c.patient_age,
            "patient_gender": c.patient_gender,
        }
        for c in body.cases
    ]

    raw_results = await ai.suggest_codes_batch(cases)

    results = []
    succeeded = 0
    failed = 0

    for case, result in zip(body.cases, raw_results):
        if isinstance(result, Exception):
            failed += 1
            results.append(BatchCodingResult(
                case_id=case.case_id,
                success=False,
                error=str(result),
            ))
        else:
            succeeded += 1
            results.append(BatchCodingResult(
                case_id=case.case_id,
                success=True,
                diagnoses=[d.model_dump() for d in result.diagnoses],
                procedures=[p.model_dump() for p in result.procedures],
                reasoning=result.reasoning,
            ))

    logger.info(
        "batch_coding_api_complete",
        user_id=str(current_user.get("user_id")),
        total=len(body.cases),
        succeeded=succeeded,
        failed=failed,
    )

    return BatchCodingResponse(
        results=results,
        total=len(body.cases),
        succeeded=succeeded,
        failed=failed,
    )


# ── Revenue Intelligence ─────────────────────────────────────────────────────

@router.post("/revenue-insights")
async def revenue_insights(
    body: RevenueInsightRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Generate AI-powered revenue cycle insights from analytics data.
    Uses claude-opus-4-6 for deep analysis and actionable recommendations.
    """
    from src.core.nlp.ai_service import get_ai_service
    ai = get_ai_service()

    try:
        insights = await ai.generate_revenue_insights(body.analytics_data)
        return insights
    except Exception as e:
        logger.error("revenue_insights_error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Revenue intelligence analysis temporarily unavailable.",
        )


# ── Stream Coding Analysis ───────────────────────────────────────────────────

@router.post("/coding/stream")
async def stream_coding(
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    """
    Stream real-time medical coding analysis for a single clinical note.
    Returns Server-Sent Events (SSE) with incremental coding suggestions.
    """
    from src.core.nlp.ai_service import get_ai_service
    ai = get_ai_service()

    clinical_text = body.get("clinical_text", "")
    encounter_type = body.get("encounter_type")

    if not clinical_text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="clinical_text is required.")

    async def _stream():
        try:
            async for chunk in ai.stream_coding_session(
                clinical_text=clinical_text,
                encounter_type=encounter_type,
            ):
                yield f"data: {json.dumps({'delta': chunk})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error("coding_stream_error", error=str(e))
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )


# ── AI Assistant -> AI Agents command channel ───────────────────────────────
import re as _re  # noqa: E402
from datetime import datetime as _dt, timezone as _tz  # noqa: E402
from sqlalchemy import select as _select  # noqa: E402

_AGENT_CANON = {
    "coding": "coding", "coder": "coding",
    "billing": "billing", "biller": "billing", "scrub": "billing",
    "posting": "payment_posting", "payment": "payment_posting", "payment_posting": "payment_posting", "era": "payment_posting",
    "denial": "ar_denial", "denials": "ar_denial", "ar_denial": "ar_denial", "appeal": "ar_denial",
    "prior": "prior_auth", "prior_auth": "prior_auth", "authorization": "prior_auth",
    "eligibility": "eligibility", "coverage": "eligibility",
    "intake": "patient_intake", "patient_intake": "patient_intake",
    "all": "*", "every": "*", "agents": "*", "everyone": "*",
}
_AGENT_TO_QUEUES = {
    "coding": ["coding"], "billing": ["billing"], "payment_posting": ["posting"],
    "ar_denial": ["denial", "follow_up"], "prior_auth": ["prior_auth", "authorization"],
    "eligibility": ["eligibility", "verification"], "patient_intake": ["intake", "patient_intake"],
}


def _detect_agent(text: str) -> str:
    for kw, canon in _AGENT_CANON.items():
        if _re.search(r"\b" + _re.escape(kw) + r"\b", text):
            return canon
    return "*"


def _parse_agent_command(instruction: str) -> dict:
    """Map a natural-language instruction to an allowlisted agent directive."""
    t = instruction.lower().strip()
    agent = _detect_agent(t)

    if any(w in t for w in ("threshold", "confidence")) or _re.search(r"(raise|lower|set).*(0?\.\d+|\d{1,3}\s*%)", t):
        m = _re.search(r"(0?\.\d+|\d{1,3}\s*%)", t)
        if m:
            raw = m.group(1).replace("%", "").strip()
            val = float(raw)
            if val > 1:
                val = val / 100.0
            val = max(0.0, min(1.0, val))
            return {"action": "set_threshold", "agent": agent, "value": round(val, 2), "destructive": True}

    if any(w in t for w in ("pause", "disable", "stop", "turn off", "shut off", "deactivate")):
        return {"action": "set_enabled", "agent": agent, "value": False, "destructive": True}
    if any(w in t for w in ("resume", "enable", "re-enable", "turn on", "activate")):
        return {"action": "set_enabled", "agent": agent, "value": True}

    if "auto" in t and any(w in t for w in ("advance", "approve", "complete")):
        on = not any(w in t for w in ("off", "disable", "stop", "do not", "don't"))
        return {"action": "set_auto_advance", "agent": agent, "value": on}

    if any(w in t for w in ("reprocess", "re-run", "rerun", "retry", "re-queue", "requeue")):
        scope = "failed" if "failed" in t else ("all" if "all" in t else "escalated")
        return {"action": "reprocess", "agent": agent, "value": scope}

    return {"action": "set_instructions", "agent": agent, "value": instruction.strip()}


async def _apply_agent_directive(db: AsyncSession, parsed: dict, current_user: dict) -> dict:
    from src.infrastructure.database.models import AgentDirective, WorkQueueItem  # noqa: PLC0415
    agent = parsed["agent"]
    action = parsed["action"]
    now = _dt.now(_tz.utc).replace(tzinfo=None)

    if action == "reprocess":
        scope = parsed["value"]
        statuses = ["escalated", "failed"] if scope == "all" else (["failed"] if scope == "failed" else ["escalated"])
        q = _select(WorkQueueItem).where(WorkQueueItem.status.in_(statuses))
        if agent != "*":
            q = q.where(WorkQueueItem.queue_type.in_(_AGENT_TO_QUEUES.get(agent, [])))
        items = (await db.execute(q)).scalars().all()
        for it in items:
            it.status = "pending"; it.started_at = None; it.completed_at = None; it.updated_at = now
        await db.commit()
        return {"applied": True, "requeued": len(items),
                "note": "Items reset to pending; the dispatch loop re-runs them through the agents."}

    cur = (await db.execute(_select(AgentDirective).where(AgentDirective.agent_type == agent))).scalar_one_or_none()
    if cur is None:
        cur = AgentDirective(agent_type=agent, enabled=True, created_at=now, updated_at=now)
        db.add(cur)
    if action == "set_threshold":
        cur.confidence_threshold = parsed["value"]
    elif action == "set_enabled":
        cur.enabled = bool(parsed["value"])
    elif action == "set_auto_advance":
        cur.auto_advance = bool(parsed["value"])
    elif action == "set_instructions":
        cur.instructions = parsed["value"]
    cur.updated_by = current_user.get("user_id")
    cur.updated_at = now
    await db.commit()
    return {"applied": True, "agent": agent, "action": action, "value": parsed["value"]}


class AgentCommandRequest(BaseModel):
    instruction: str
    confirm: bool = False


@router.post("/agent-command")
async def agent_command(
    body: AgentCommandRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Interpret a natural-language instruction and apply it to the AI agents
    (enable/pause, confidence threshold, auto-advance, standing instruction, reprocess)."""
    if current_user.get("user_type") != "internal":
        raise HTTPException(status_code=403, detail="Only internal staff can direct the agents.")
    if not body.instruction.strip():
        raise HTTPException(status_code=400, detail="instruction is required")
    parsed = _parse_agent_command(body.instruction)
    if parsed.get("destructive") and not body.confirm:
        # Require explicit confirmation for pause / threshold changes (server-side gate).
        agent = "all agents" if parsed["agent"] == "*" else parsed["agent"]
        if parsed["action"] == "set_enabled":
            summary = f"pause {agent} — its work items will route to humans"
        else:
            summary = f"change the {agent} confidence threshold to {parsed['value']}"
        raise HTTPException(
            status_code=409,
            detail={"requires_confirmation": True, "parsed": parsed,
                    "message": f"This command will {summary}. Resend with confirm=true to apply."},
        )
    result = await _apply_agent_directive(db, parsed, current_user)
    logger.info("ai_assistant.agent_command", instruction=body.instruction,
                parsed=parsed, confirmed=body.confirm)
    return {"instruction": body.instruction, "parsed": parsed, "result": result}


@router.get("/agent-directives")
async def list_agent_directives(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    from src.infrastructure.database.models import AgentDirective  # noqa: PLC0415
    rows = (await db.execute(_select(AgentDirective))).scalars().all()
    return {"directives": [{
        "agent_type": r.agent_type, "enabled": r.enabled,
        "confidence_threshold": r.confidence_threshold, "auto_advance": r.auto_advance,
        "instructions": r.instructions, "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    } for r in rows]}
