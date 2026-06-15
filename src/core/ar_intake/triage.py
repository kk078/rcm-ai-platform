"""AI triage of imported open-AR (external_ar) follow-up items.

For each aged, unpaid claim line the AR agent recommends the single best next action
(rebill, corrected claim, appeal, call payer, secondary billing, patient balance,
write-off, resolve credit) with a short rationale and confidence. The recommendation is
merged INTO the item's notes JSON (preserving the AR fields the Open AR page needs).

Runs as a throttled Celery beat task so a large backlog is triaged gradually, not all at
once. Items already triaged (notes has 'recommendation') are skipped.
"""
from __future__ import annotations

import json

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models import WorkQueueItem

logger = structlog.get_logger()

ACTIONS = (
    "rebill", "corrected_claim", "appeal", "call_payer",
    "secondary_billing", "patient_balance", "adjust_writeoff", "resolve_credit",
)

_SYSTEM = (
    "You are an AR follow-up specialist for U.S. medical billing. Given ONE aged, unpaid "
    "claim line from a provider's aging report, recommend the single best next action to "
    "resolve it and explain briefly (think like a biller working the AR by age and payer). "
    "Choose recommended_action from EXACTLY this set: "
    + ", ".join(ACTIONS) + ". Guidance: very old (>120d) past timely filing often → appeal "
    "with proof of timely filing or adjust_writeoff; missing/needs info → corrected_claim or "
    "rebill; no payer response → call_payer; primary paid, balance remains → secondary_billing "
    "or patient_balance; negative balance → resolve_credit. "
    'Return ONLY JSON: {"recommended_action":"...","reasoning":"one sentence","confidence":0.0-1.0}.'
)


async def recommend_action(ar: dict) -> dict:
    """LLM recommendation for one AR line. Best-effort -> {} on failure."""
    if ar.get("is_credit"):
        return {"recommended_action": "resolve_credit",
                "reasoning": "Negative balance — research the overpayment and refund or adjust.",
                "confidence": 0.9}
    facts = (
        f"payer={ar.get('payer')}; balance={ar.get('balance')}; charges={ar.get('charges')}; "
        f"aging_days={ar.get('aging_days')}; bucket={ar.get('bucket')}; "
        f"service_date={ar.get('service_date')}; last_submission={ar.get('last_submission')}"
    )
    try:
        from src.core.nlp.ai_service import get_ai_service  # noqa: PLC0415
        backend = get_ai_service()._get_backend()
        out, _ = await backend.call(system=_SYSTEM, user_content="AR line:\n" + facts,
                                    use_json=False, max_tokens=250)
        import re  # noqa: PLC0415
        m = re.search(r"\{.*\}", out or "", re.DOTALL)
        if not m:
            return {}
        data = json.loads(m.group(0))
        act = data.get("recommended_action")
        if act not in ACTIONS:
            act = "call_payer"
        return {"recommended_action": act,
                "reasoning": (data.get("reasoning") or "").strip()[:400],
                "confidence": float(data.get("confidence") or 0.5)}
    except Exception as e:  # noqa: BLE001
        logger.warning("ar_triage_failed", error=str(e))
        return {}


async def triage_pending(db: AsyncSession, limit: int = 100, practice_id=None) -> dict:
    """Triage up to `limit` un-triaged pending external_ar items. Merges the rec into notes.
    Optionally scoped to one practice (used by the on-demand 'Triage now' action)."""
    conds = [WorkQueueItem.item_type == "external_ar", WorkQueueItem.status == "pending"]
    if practice_id is not None:
        conds.append(WorkQueueItem.practice_id == practice_id)
    rows = (await db.execute(
        select(WorkQueueItem).where(*conds)
        .order_by(WorkQueueItem.priority.desc()).limit(limit * 3)
    )).scalars().all()

    triaged = 0
    for it in rows:
        if triaged >= limit:
            break
        try:
            ar = json.loads(it.notes or "{}")
        except (ValueError, TypeError):
            continue
        if ar.get("recommendation"):
            continue  # already triaged
        rec = await recommend_action(ar)
        if not rec:
            continue
        ar["recommendation"] = rec.get("recommended_action")
        ar["rec_reasoning"] = rec.get("reasoning")
        ar["rec_confidence"] = rec.get("confidence")
        it.notes = json.dumps(ar)
        triaged += 1

    await db.flush()
    logger.info("ar_triage_batch", triaged=triaged, scanned=len(rows))
    return {"triaged": triaged, "scanned": len(rows)}
