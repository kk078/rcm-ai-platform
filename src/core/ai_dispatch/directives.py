"""Effective AI-agent directives (merge global \'*\' under the specific agent).

Used by the dispatcher to enforce assistant/admin instructions: enable/pause,
confidence threshold, auto-advance, and standing natural-language instructions.
"""
from __future__ import annotations

from sqlalchemy import select


async def load_effective(db, agent_type: str) -> dict:
    from src.infrastructure.database.models import AgentDirective  # noqa: PLC0415
    rows = (await db.execute(
        select(AgentDirective).where(AgentDirective.agent_type.in_([agent_type, "*"]))
    )).scalars().all()
    by = {r.agent_type: r for r in rows}
    g, sp = by.get("*"), by.get(agent_type)

    # enabled: specific wins, else global, else True
    enabled = True
    for r in (sp, g):
        if r is not None:
            enabled = bool(r.enabled); break

    # threshold: first non-null (specific then global); None -> caller uses default
    threshold = None
    for r in (sp, g):
        if r is not None and r.confidence_threshold is not None:
            threshold = float(r.confidence_threshold); break

    auto_advance = False
    for r in (sp, g):
        if r is not None:
            auto_advance = bool(r.auto_advance); break

    instr = []
    if g is not None and g.instructions:
        instr.append(g.instructions.strip())
    if sp is not None and sp.instructions:
        instr.append(sp.instructions.strip())

    return {"enabled": enabled, "threshold": threshold,
            "auto_advance": auto_advance, "instructions": "\n".join(instr)}
