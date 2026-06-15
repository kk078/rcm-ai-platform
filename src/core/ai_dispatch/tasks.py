"""
Celery tasks for autonomous AI dispatch.

Two tasks:
  1. dispatch_work_item_to_ai(item_id)   — process a single item via AI agents.
  2. dispatch_pending_ai_items()         — beat task; fans out all pending items.

WorkQueueItem is an indirection record (item_type + item_id pointer).  Clinical
fields are fetched via async DB joins inside _build_item_data() so the AI
agents receive a rich, fully-populated payload.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from celery import shared_task
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.infrastructure.database.session import async_session as async_session_factory
from src.config import get_settings

settings = get_settings()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run an async coroutine synchronously inside a Celery worker.

    Uses asyncio.run() which creates a fresh event loop each call.
    asyncio.get_event_loop() is deprecated in Python 3.10+ and raises
    RuntimeError in 3.12+ when no running loop exists (common in Celery workers).
    """
    return asyncio.run(coro)


async def _mark_failed(item_id: str, exc: BaseException) -> None:
    """Dead-letter a work item that has exhausted all Celery retries.

    Sets status='failed' and writes a structured JSON note so operators can
    triage without digging through logs.
    """
    from src.infrastructure.database.models import WorkQueueItem  # noqa: PLC0415

    async with async_session_factory() as db:
        item = await db.get(WorkQueueItem, item_id)
        if item:
            item.status = "failed"
            item.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            item.notes = json.dumps({
                "source": "ai_dispatch",
                "outcome": "failed",
                "error": str(exc),
                "error_type": type(exc).__name__,
                "message": "Dead-lettered after all Celery retries exhausted.",
            })[:2000]
            await db.commit()
            logger.error(
                "ai_dispatch: item %s dead-lettered — %s: %s",
                item_id, type(exc).__name__, exc,
            )


async def _maybe_build_claim_form(work_item_id: str, item_type: str, item_ref_id: str | None) -> int | None:
    """Roadmap B — coding/billing -> claim-form feedback loop.

    When a claim work item is processed, auto-assemble the enriched + scrubbed
    CMS-1500 (reusing src.core.claim_forms) so the review screen is pre-populated,
    and feed the scrub edits back onto the work item's agent trace.
    Returns the number of scrub edits, or None if not applicable / failed.
    """
    if item_type != "claim" or not item_ref_id:
        return None
    try:
        from src.core.claim_forms.assembler import assemble_claim_form  # noqa: PLC0415
        from src.infrastructure.database.models import Claim, ClaimForm, WorkQueueItem  # noqa: PLC0415
        async with async_session_factory() as db:
            assembled = await assemble_claim_form(db, item_ref_id, "cms1500")
            claim = (await db.execute(select(Claim).where(Claim.id == item_ref_id))).scalar_one_or_none()
            if claim is None:
                return None
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            cf = (await db.execute(
                select(ClaimForm).where(ClaimForm.claim_id == item_ref_id, ClaimForm.form_type == "cms1500")
            )).scalar_one_or_none()
            if cf is None:
                db.add(ClaimForm(claim_id=claim.id, practice_id=claim.practice_id, form_type="cms1500",
                                 fields=assembled["form"], edits=assembled["edits"],
                                 enrichment=assembled["enrichment"], status="draft",
                                 created_at=now, updated_at=now))
            else:
                cf.fields = assembled["form"]; cf.edits = assembled["edits"]
                cf.enrichment = assembled["enrichment"]; cf.status = "draft"; cf.updated_at = now
            # Feed the scrub result back onto the work item's trace.
            edits = assembled["edits"]
            errs = sum(1 for e in edits if e.get("severity") == "error")
            wi = await db.get(WorkQueueItem, work_item_id)
            if wi is not None:
                trace = list(wi.agent_trace or [])
                trace.append({"seq": len(trace) + 1, "label": "Claim form auto-assembled (CMS-1500)",
                              "status": "warning" if errs else "done",
                              "detail": f"{len(edits)} scrub edit(s), {errs} blocking — ready for review"})
                wi.agent_trace = trace
            await db.commit()
            return len(edits)
    except Exception:  # noqa: BLE001
        logger.exception("ai_dispatch: auto claim-form build failed for %s", item_ref_id)
        return None


async def _fetch_charge_entry_data(db, item_id: str) -> dict[str, Any]:
    """Enrich payload for charge-entry items (coding / billing / intake)."""
    from src.infrastructure.database.models import ChargeEntry, Patient, Payer  # noqa: PLC0415

    stmt = select(ChargeEntry).where(ChargeEntry.id == item_id)
    result = await db.execute(stmt)
    charge = result.scalar_one_or_none()
    if charge is None:
        return {}

    # Optional: resolve patient & payer names for richer context.
    patient_dob = None
    if charge.patient_id:
        p_stmt = select(Patient).where(Patient.id == charge.patient_id)
        p_result = await db.execute(p_stmt)
        patient = p_result.scalar_one_or_none()
        if patient:
            patient_dob = str(patient.date_of_birth) if patient.date_of_birth else None

    payer_name = None
    if charge.primary_payer_id:
        py_stmt = select(Payer).where(Payer.id == charge.primary_payer_id)
        py_result = await db.execute(py_stmt)
        payer = py_result.scalar_one_or_none()
        if payer:
            payer_name = payer.payer_name

    return {
        "charge_entry_id": str(charge.id),
        "patient_id": str(charge.patient_id) if charge.patient_id else None,
        "patient_dob": patient_dob,
        "service_date": str(charge.service_date) if charge.service_date else None,
        "rendering_provider_id": str(charge.rendering_provider_id) if charge.rendering_provider_id else None,
        "diagnosis_codes": charge.diagnosis_codes or [],
        "procedure_codes": charge.procedure_codes or {},
        "clinical_notes": charge.clinical_notes or "",
        "member_id": charge.member_id or "",
        "authorization_number": charge.authorization_number or "",
        "primary_payer_id": str(charge.primary_payer_id) if charge.primary_payer_id else None,
        "payer_name": payer_name or "",
    }


async def _fetch_coding_session_data(db, item_id: str) -> dict[str, Any]:
    """Enrich payload for coding-session items."""
    from src.infrastructure.database.models import CodingSession, Encounter  # noqa: PLC0415

    stmt = select(CodingSession).where(CodingSession.id == item_id)
    result = await db.execute(stmt)
    session = result.scalar_one_or_none()
    if session is None:
        return {}

    encounter_data: dict[str, Any] = {}
    if session.encounter_id:
        enc_stmt = select(Encounter).where(Encounter.id == session.encounter_id)
        enc_result = await db.execute(enc_stmt)
        encounter = enc_result.scalar_one_or_none()
        if encounter:
            encounter_data = {
                "encounter_id": str(encounter.id),
                "encounter_type": encounter.encounter_type or "",
                "encounter_date": str(encounter.encounter_date) if encounter.encounter_date else None,
                "provider_id": str(encounter.provider_id) if encounter.provider_id else None,
                "encounter_notes": encounter.notes or "",
                "prior_auth_number": encounter.prior_auth_number or "",
            }

    return {
        "coding_session_id": str(session.id),
        "suggested_codes": session.suggested_codes or [],
        "final_codes": session.final_codes or [],
        "nlp_extraction": session.nlp_extraction or {},
        "ai_model_version": session.ai_model_version or "",
        **encounter_data,
    }


async def _fetch_claim_data(db, item_id: str) -> dict[str, Any]:
    """Enrich payload for claim items (billing / denial / follow-up)."""
    from src.infrastructure.database.models import (  # noqa: PLC0415
        Claim, ClaimLine, ClaimDiagnosis, Payer, Coverage,
    )

    stmt = select(Claim).where(Claim.id == item_id)
    result = await db.execute(stmt)
    claim = result.scalar_one_or_none()
    if claim is None:
        return {}

    # Claim lines
    lines_stmt = select(ClaimLine).where(ClaimLine.claim_id == claim.id)
    lines_result = await db.execute(lines_stmt)
    lines = lines_result.scalars().all()
    def _mods(ln):
        return [m for m in (ln.modifier_1, ln.modifier_2, ln.modifier_3, ln.modifier_4) if m]
    def _ptrs(ln):
        return [p for p in (ln.icd_pointer_1, ln.icd_pointer_2, ln.icd_pointer_3, ln.icd_pointer_4) if p]
    lines_data = [
        {
            "cpt_code": ln.cpt_code or "",
            "modifiers": _mods(ln),
            "icd_pointers": _ptrs(ln),
            "charge_amount": float(ln.charge_amount) if ln.charge_amount else 0.0,
        }
        for ln in lines
    ]

    # Claim diagnoses
    dx_stmt = select(ClaimDiagnosis).where(ClaimDiagnosis.claim_id == claim.id).order_by(ClaimDiagnosis.sequence_number)
    dx_result = await db.execute(dx_stmt)
    diagnoses = dx_result.scalars().all()
    dx_data = [
        {
            "icd10_code": dx.icd10_code or "",
            "sequence_number": dx.sequence_number,
            "is_principal": dx.is_principal,
        }
        for dx in diagnoses
    ]

    # Payer
    payer_name = ""
    if claim.payer_id:
        py_stmt = select(Payer).where(Payer.id == claim.payer_id)
        py_result = await db.execute(py_stmt)
        payer = py_result.scalar_one_or_none()
        if payer:
            payer_name = payer.payer_name

    # Coverage
    coverage_data: dict[str, Any] = {}
    if claim.coverage_id:
        cov_stmt = select(Coverage).where(Coverage.id == claim.coverage_id)
        cov_result = await db.execute(cov_stmt)
        coverage = cov_result.scalar_one_or_none()
        if coverage:
            coverage_data = {
                "member_id": coverage.member_id or "",
                "group_number": coverage.group_number or "",
                "plan_name": coverage.plan_name or "",
                "plan_type": coverage.plan_type or "",
            }

    return {
        "claim_id": str(claim.id),
        "claim_number": claim.claim_number or "",
        "claim_status": claim.status or "",
        "total_charge": float(claim.total_charge) if claim.total_charge else 0.0,
        "payer_id": str(claim.payer_id) if claim.payer_id else None,
        "payer_name": payer_name,
        "claim_lines": lines_data,
        "diagnoses": dx_data,
        # Aliases for the agent service's _build_case / handlers (contract drift fix):
        "cpt_codes": [{"code": l["cpt_code"], "modifiers": l["modifiers"]} for l in lines_data if l["cpt_code"]],
        "icd_codes": [d["icd10_code"] for d in dx_data if d["icd10_code"]],
        "patient_member_id": coverage_data.get("member_id", ""),
        **coverage_data,
    }


async def _fetch_denial_data(db, item_id: str) -> dict[str, Any]:
    """Enrich payload for denial items."""
    from src.infrastructure.database.models import Denial, Payer  # noqa: PLC0415

    stmt = select(Denial).where(Denial.id == item_id)
    result = await db.execute(stmt)
    denial = result.scalar_one_or_none()
    if denial is None:
        return {}

    payer_name = ""
    if denial.payer_id:
        py_stmt = select(Payer).where(Payer.id == denial.payer_id)
        py_result = await db.execute(py_stmt)
        payer = py_result.scalar_one_or_none()
        if payer:
            payer_name = payer.payer_name

    return {
        "denial_id": str(denial.id),
        "reason_code": denial.reason_code or "",      # CARC
        "remark_codes": denial.remark_codes or [],    # RARC list
        "denial_amount": float(denial.denial_amount) if denial.denial_amount else 0.0,
        "category": denial.category or "",
        "root_cause": denial.root_cause or "",
        "appeal_deadline": str(denial.appeal_deadline) if denial.appeal_deadline else None,
        "payer_id": str(denial.payer_id) if denial.payer_id else None,
        "payer_name": payer_name,
    }


async def _fetch_payment_batch_data(db, item_id: str) -> dict[str, Any]:
    """Enrich payload for payment-posting items."""
    from src.infrastructure.database.models import PaymentBatch  # noqa: PLC0415

    stmt = select(PaymentBatch).where(PaymentBatch.id == item_id)
    result = await db.execute(stmt)
    batch = result.scalar_one_or_none()
    if batch is None:
        return {}

    return {
        "payment_batch_id": str(batch.id),
        "payment_date": str(batch.payment_date) if batch.payment_date else None,
        "total_payment": float(batch.total_payment) if hasattr(batch, "total_payment") and batch.total_payment else 0.0,
        "check_number": getattr(batch, "check_number", "") or "",
        "payer_id": str(batch.payer_id) if hasattr(batch, "payer_id") and batch.payer_id else None,
        "era_835_data": getattr(batch, "era_835_data", {}) or {},
    }


# item_type → enrichment coroutine
_ITEM_TYPE_FETCHERS = {
    "charge_entry":    _fetch_charge_entry_data,
    "coding_session":  _fetch_coding_session_data,
    "claim":           _fetch_claim_data,
    "denial":          _fetch_denial_data,
    "payment_batch":   _fetch_payment_batch_data,
}


async def _build_item_data(db, item) -> dict[str, Any]:
    """Build the payload forwarded to the AI agent service.

    The base fields come from WorkQueueItem.  Additional clinical context is
    fetched by joining to the entity identified by (item_type, item_id).
    """
    base: dict[str, Any] = {
        "id":          str(item.id),
        "queue_type":  item.queue_type,
        "item_type":   item.item_type or "",
        "item_id":     str(item.item_id) if item.item_id else None,
        "priority":    item.priority if item.priority is not None else 5,
        "practice_id": str(item.practice_id) if item.practice_id else None,
        "assigned_to": str(item.assigned_to) if item.assigned_to else None,
        "due_date":    str(item.due_date) if item.due_date else None,
        "sla_breached": bool(item.sla_breached) if item.sla_breached is not None else False,
        "notes":       item.notes or "",
    }

    # Enrich with entity-specific clinical fields.
    fetcher = _ITEM_TYPE_FETCHERS.get(item.item_type or "")
    if fetcher and item.item_id:
        try:
            entity_data = await fetcher(db, str(item.item_id))
            base.update(entity_data)
        except Exception:  # noqa: BLE001
            logger.exception(
                "ai_dispatch: failed to enrich item %s (item_type=%s item_id=%s)",
                item.id, item.item_type, item.item_id,
            )
            # Continue with base payload — agent will work with what it has.
    else:
        if item.item_type and item.item_type not in _ITEM_TYPE_FETCHERS:
            logger.warning(
                "ai_dispatch: no enrichment fetcher for item_type='%s' on item %s",
                item.item_type, item.id,
            )

    return base


# ---------------------------------------------------------------------------
# All queue types that should be dispatched automatically.
# Keep in sync with QUEUE_TYPE_TO_AGENT in dispatcher.py.
# ---------------------------------------------------------------------------
DISPATCHABLE_QUEUE_TYPES: frozenset[str] = frozenset({
    "coding",
    "billing",
    "posting",
    "denial",
    "follow_up",
    "intake",
    "prior_auth",
    "authorization",
    "eligibility",
    "verification",
    "patient_intake",
})


# ---------------------------------------------------------------------------
# Task 1: process a single work item
# ---------------------------------------------------------------------------

@shared_task(
    name="src.core.ai_dispatch.tasks.dispatch_work_item_to_ai",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    acks_late=True,
)
def dispatch_work_item_to_ai(self, item_id: str) -> dict[str, Any]:
    """Fetch a WorkQueueItem, run it through the AI agent, update status.

    Returns a summary dict for logging / monitoring.  On unrecoverable failure
    (retries exhausted) the item is dead-lettered to status='failed' so it
    surfaces in the human review queue rather than silently disappearing.
    """
    if not getattr(settings, "ai_agent_enabled", True):
        logger.info("ai_dispatch: AI processing disabled, skipping item %s", item_id)
        return {"skipped": True, "item_id": item_id}

    try:
        return _run(_process_item(self, item_id))
    except Exception as exc:  # noqa: BLE001
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        # All retries exhausted — dead-letter the item.
        _run(_mark_failed(item_id, exc))
        return {"item_id": item_id, "outcome": "failed", "error": str(exc)}


async def _process_item(task_self, item_id: str) -> dict[str, Any]:
    # Deferred imports to avoid circular deps at module load time.
    from src.infrastructure.database.models import WorkQueueItem  # noqa: PLC0415
    from .dispatcher import dispatch_item, QUEUE_TYPE_TO_AGENT  # noqa: PLC0415
    from .directives import load_effective  # noqa: PLC0415

    async with async_session_factory() as db:
        # Fetch with optimistic status check.
        stmt = select(WorkQueueItem).where(WorkQueueItem.id == item_id)
        result = await db.execute(stmt)
        item = result.scalar_one_or_none()

        if item is None:
            logger.warning("ai_dispatch: item %s not found", item_id)
            return {"item_id": item_id, "outcome": "not_found"}

        if item.status not in ("pending",):
            logger.info(
                "ai_dispatch: item %s already in status '%s', skipping",
                item_id, item.status,
            )
            return {"item_id": item_id, "outcome": "skipped", "status": item.status}

        # Guard: only dispatch known queue types.
        if item.queue_type not in DISPATCHABLE_QUEUE_TYPES:
            logger.info(
                "ai_dispatch: item %s queue_type='%s' not in dispatchable set, skipping",
                item_id, item.queue_type,
            )
            return {"item_id": item_id, "outcome": "skipped", "reason": "queue_type_not_dispatchable"}

        # ── Agent directive enforcement (AI Assistant control plane) ──────────
        agent_type = QUEUE_TYPE_TO_AGENT.get(item.queue_type, item.queue_type)
        eff = await load_effective(db, agent_type)
        if not eff["enabled"]:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            item.status = "escalated"
            item.agent_trace = [{"seq": 1, "label": "Agent paused by directive", "status": "warning",
                                 "detail": f"{agent_type} is disabled via AI Assistant directive — routed to human."}]
            item.notes = json.dumps({"source": "ai_dispatch", "outcome": "escalated",
                                     "agent_type": agent_type, "confidence": 0.0,
                                     "message": "Agent paused by directive — routed to human review."})[:2000]
            item.updated_at = now
            await db.commit()
            logger.info("ai_dispatch: item %s escalated — agent '%s' paused by directive", item_id, agent_type)
            return {"item_id": item_id, "outcome": "escalated", "reason": "agent_paused", "agent_type": agent_type}
        eff_threshold = eff["threshold"]

        # Mark in_progress — optimistic lock; other workers will skip.
        item.status = "in_progress"
        item.started_at = datetime.now(timezone.utc).replace(tzinfo=None)
        item.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await db.commit()

        # Build enriched payload while the session is still open.
        item_data = await _build_item_data(db, item)
        if eff["instructions"]:
            item_data["agent_instructions"] = eff["instructions"]

    # Dispatch OUTSIDE the session so the DB lock is released while the LLM runs.
    async with async_session_factory() as db:
        from src.infrastructure.database.models import WorkQueueItem  # noqa: PLC0415

        dispatch_result = await dispatch_item(item.queue_type, item_data, threshold_override=eff_threshold)

        # Re-fetch to apply outcome (item may have been touched by another path).
        stmt = select(WorkQueueItem).where(WorkQueueItem.id == item_id)
        result = await db.execute(stmt)
        item = result.scalar_one_or_none()

        if item is None:
            logger.error("ai_dispatch: item %s vanished after dispatch", item_id)
            return {"item_id": item_id, "outcome": "disappeared_after_dispatch"}

        now = datetime.now(timezone.utc).replace(tzinfo=None)

        # Append a directive-aware final decision step so the trace reflects the
        # effective (dispatcher-level) outcome, not just the agent's own threshold.
        _steps = list(dispatch_result.steps or [])
        _eff = f"effective threshold {eff_threshold:.2f}" if eff_threshold is not None else "default threshold"
        _steps.append({"seq": len(_steps) + 1, "label": "Pipeline decision (directive-aware)",
                       "status": "warning" if dispatch_result.escalate else "done",
                       "detail": (("escalated to human review" if dispatch_result.escalate else "auto-completed")
                                  + f" — confidence {dispatch_result.confidence:.2f}, {_eff}")})
        dispatch_result.steps = _steps

        if dispatch_result.escalate:
            item.status = "escalated"
            item.agent_trace = dispatch_result.steps or None
            item.notes = json.dumps({
                "source": "ai_dispatch",
                "outcome": "escalated",
                "agent_type": dispatch_result.agent_type,
                "confidence": round(dispatch_result.confidence, 4),
                "error_code": dispatch_result.error_code or None,
                "retry_count": dispatch_result.retry_count,
                "duration_ms": dispatch_result.duration_ms,
                "message": dispatch_result.notes,
            })[:2000]
            outcome = "escalated"
        else:
            item.status = "completed"
            item.completed_at = now
            item.agent_trace = dispatch_result.steps or None
            item.notes = json.dumps({
                "source": "ai_dispatch",
                "outcome": "completed",
                "agent_type": dispatch_result.agent_type,
                "confidence": round(dispatch_result.confidence, 4),
                "retry_count": dispatch_result.retry_count,
                "duration_ms": dispatch_result.duration_ms,
                "message": dispatch_result.notes,
            })[:2000]
            outcome = "completed"

        item.updated_at = now
        await db.commit()

    # Roadmap B: auto-assemble the enriched, scrubbed claim form + feed edits back.
    await _maybe_build_claim_form(item_id, item_data.get("item_type"), item_data.get("item_id"))

    logger.info(
        "ai_dispatch: item %s → %s (queue=%s agent=%s confidence=%.2f)",
        item_id, outcome, item_data.get("queue_type"), dispatch_result.agent_type, dispatch_result.confidence,
    )
    return {
        "item_id":    item_id,
        "outcome":    outcome,
        "queue_type": item_data.get("queue_type"),
        "item_type":  item_data.get("item_type"),
        "agent_type": dispatch_result.agent_type,
        "confidence": dispatch_result.confidence,
    }


# ---------------------------------------------------------------------------
# Task 2: beat fan-out — dispatch all pending items
# ---------------------------------------------------------------------------

@shared_task(name="src.core.ai_dispatch.tasks.dispatch_pending_ai_items")
def dispatch_pending_ai_items() -> dict[str, Any]:
    """Query all pending WorkQueueItems and fire dispatch_work_item_to_ai for each.

    Runs every 5 minutes via Celery Beat.
    """
    if not getattr(settings, "ai_agent_enabled", True):
        logger.info("ai_dispatch: AI processing disabled, skipping beat dispatch")
        return {"dispatched": 0}

    return _run(_fan_out())


async def _fan_out() -> dict[str, Any]:
    from src.infrastructure.database.models import WorkQueueItem  # noqa: PLC0415

    async with async_session_factory() as db:
        stmt = (
            select(WorkQueueItem.id)
            .where(
                WorkQueueItem.status == "pending",
                WorkQueueItem.queue_type.in_(DISPATCHABLE_QUEUE_TYPES),
            )
            .order_by(
                WorkQueueItem.priority.asc(),    # lower number = higher urgency
                WorkQueueItem.due_date.asc().nulls_last(),
            )
            .limit(500)  # safety cap per beat cycle
        )
        result = await db.execute(stmt)
        item_ids = [str(row[0]) for row in result.fetchall()]

    dispatched = 0
    for i, item_id in enumerate(item_ids):
        # Stagger dispatch: 10 tasks per second (countdown=i//10 seconds).
        # This prevents a thundering herd of 500 simultaneous LLM calls when
        # the beat fires, spreading load over ~50 seconds instead.
        dispatch_work_item_to_ai.apply_async(args=[item_id], countdown=i // 10)
        dispatched += 1

    logger.info(
        "ai_dispatch: beat fan-out dispatched %d items (queue_types=%s)",
        dispatched,
        sorted(DISPATCHABLE_QUEUE_TYPES),
    )
    return {"dispatched": dispatched, "item_ids": item_ids}
