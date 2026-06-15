"""
Admin API — feature flags, canary releases, system health, and metrics.
All endpoints require internal company_admin role.
"""

from __future__ import annotations

import platform
import sys
import time

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel

from src.infrastructure.auth.middleware import get_current_user

logger = structlog.get_logger()
router = APIRouter()

_APP_START = time.time()


def _require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("internal_role") not in ("company_admin", "super_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return current_user


# ── System Info ───────────────────────────────────────────────────────────────

@router.get("/system")
async def system_info(_: dict = Depends(_require_admin)):
    """System information and uptime."""
    uptime_s = int(time.time() - _APP_START)
    return {
        "python_version": sys.version,
        "platform": platform.platform(),
        "uptime_seconds": uptime_s,
        "uptime_human": f"{uptime_s // 3600}h {(uptime_s % 3600) // 60}m",
    }


# ── Feature Flags ─────────────────────────────────────────────────────────────

class FlagUpdate(BaseModel):
    enabled: bool
    rollout_pct: int = 100
    variants: list[str] | None = None


@router.get("/flags")
async def list_flags(_: dict = Depends(_require_admin)):
    """List all feature flags and their current state."""
    from src.core.observability.feature_flags import feature_flags
    return await feature_flags.get_all_flags()


@router.get("/flags/{flag_name}")
async def get_flag(flag_name: str, user_id: str | None = None, _: dict = Depends(_require_admin)):
    """Get a single flag state, optionally evaluated for a user."""
    from src.core.observability.feature_flags import feature_flags
    flags = await feature_flags.get_all_flags()
    if flag_name not in flags:
        raise HTTPException(status_code=404, detail=f"Flag '{flag_name}' not found")
    result = {"flag": flag_name, "config": flags[flag_name]}
    if user_id:
        result["enabled_for_user"] = await feature_flags.is_enabled(flag_name, user_id)
    return result


@router.put("/flags/{flag_name}")
async def update_flag(flag_name: str, body: FlagUpdate, _: dict = Depends(_require_admin)):
    """Create or update a feature flag."""
    from src.core.observability.feature_flags import feature_flags
    config = {"enabled": body.enabled, "rollout_pct": body.rollout_pct}
    if body.variants:
        config["variants"] = body.variants
    success = await feature_flags.set_flag(flag_name, config)
    if not success:
        raise HTTPException(status_code=503, detail="Failed to update flag in Redis")
    logger.info("admin_flag_updated", flag=flag_name, config=config)
    return {"flag": flag_name, "config": config, "updated": True}


@router.delete("/flags/{flag_name}")
async def disable_flag(flag_name: str, _: dict = Depends(_require_admin)):
    """Disable a feature flag immediately."""
    from src.core.observability.feature_flags import feature_flags
    await feature_flags.set_flag(flag_name, {"enabled": False, "rollout_pct": 0})
    return {"flag": flag_name, "disabled": True}


# ── Canary Releases ───────────────────────────────────────────────────────────

class CanaryUpdate(BaseModel):
    rollout_pct: int


@router.get("/canary")
async def list_canaries(_: dict = Depends(_require_admin)):
    """List all canary release configurations."""
    from src.core.observability.canary import canary_router
    return await canary_router.get_all_canaries()


@router.put("/canary/{canary_name}/rollout")
async def update_canary_rollout(
    canary_name: str, body: CanaryUpdate, _: dict = Depends(_require_admin)
):
    """Update canary rollout percentage (0=fully stable, 100=all canary)."""
    from src.core.observability.canary import canary_router
    success = await canary_router.set_rollout(canary_name, body.rollout_pct)
    if not success:
        raise HTTPException(status_code=503, detail="Failed to update canary in Redis")
    logger.info("admin_canary_updated", canary=canary_name, pct=body.rollout_pct)
    return {"canary": canary_name, "rollout_pct": body.rollout_pct}


@router.post("/canary/{canary_name}/rollback")
async def rollback_canary(canary_name: str, _: dict = Depends(_require_admin)):
    """Immediately rollback canary to 0% (all traffic to stable)."""
    from src.core.observability.canary import canary_router
    await canary_router.set_rollout(canary_name, 0)
    logger.warning("admin_canary_rollback", canary=canary_name)
    return {"canary": canary_name, "rollout_pct": 0, "status": "rolled_back"}


# ── Metrics endpoint ──────────────────────────────────────────────────────────

@router.get("/metrics")
async def prometheus_metrics():
    """Prometheus metrics endpoint (plain text format)."""
    try:
        from src.core.observability.metrics import generate_latest, CONTENT_TYPE_LATEST
        data = generate_latest()
        return Response(content=data, media_type=CONTENT_TYPE_LATEST)
    except Exception as e:
        logger.error("metrics_export_failed", error=str(e))
        return Response(content="# metrics unavailable\n", media_type="text/plain")


# ── A/B Test Reporting ────────────────────────────────────────────────────────

@router.get("/ab-tests")
async def list_ab_tests(_: dict = Depends(_require_admin)):
    """List active A/B tests with variant definitions."""
    from src.core.observability.feature_flags import feature_flags, DEFAULT_FLAGS
    all_flags = await feature_flags.get_all_flags()
    ab_tests = {
        name: cfg
        for name, cfg in all_flags.items()
        if "variants" in cfg and cfg.get("enabled")
    }
    return {"active_tests": ab_tests, "count": len(ab_tests)}


@router.get("/ab-tests/{flag_name}/assignment")
async def get_ab_assignment(flag_name: str, user_id: str, _: dict = Depends(_require_admin)):
    """Get variant assignment for a specific user in an A/B test."""
    from src.core.observability.feature_flags import feature_flags
    variant = await feature_flags.get_variant(flag_name, user_id)
    return {"flag": flag_name, "user_id": user_id, "variant": variant}


# ── AI Agent health (roadmap C) ─────────────────────────────────────────────
@router.get("/agent-health")
async def agent_health(
    days: int = 30,
    current_user: dict = Depends(_require_admin),
):
    """Per-agent success/escalation/confidence/error aggregates from processed work items."""
    import json as _json
    from datetime import datetime, timedelta, timezone
    from collections import defaultdict
    from sqlalchemy import select
    from src.infrastructure.database.session import async_session
    from src.infrastructure.database.models import WorkQueueItem

    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    agg: dict = defaultdict(lambda: {"processed": 0, "completed": 0, "escalated": 0,
                                     "failed": 0, "conf_sum": 0.0, "conf_n": 0,
                                     "dur_sum": 0, "dur_n": 0, "errors": defaultdict(int)})
    async with async_session() as db:
        rows = (await db.execute(
            select(WorkQueueItem).where(WorkQueueItem.updated_at >= since,
                                        WorkQueueItem.status.in_(["completed", "escalated", "failed"]))
        )).scalars().all()
    for it in rows:
        try:
            meta = _json.loads(it.notes) if it.notes else {}
        except (ValueError, TypeError):
            meta = {}
        at = meta.get("agent_type") or "unknown"
        a = agg[at]; a["processed"] += 1
        if it.status == "completed": a["completed"] += 1
        elif it.status == "escalated": a["escalated"] += 1
        elif it.status == "failed": a["failed"] += 1
        if isinstance(meta.get("confidence"), (int, float)):
            a["conf_sum"] += float(meta["confidence"]); a["conf_n"] += 1
        if isinstance(meta.get("duration_ms"), (int, float)):
            a["dur_sum"] += int(meta["duration_ms"]); a["dur_n"] += 1
        ec = meta.get("error_code")
        if ec: a["errors"][ec] += 1

    agents = []
    for name, a in sorted(agg.items()):
        p = a["processed"] or 1
        agents.append({
            "agent_type": name,
            "processed": a["processed"],
            "completed": a["completed"],
            "escalated": a["escalated"],
            "failed": a["failed"],
            "auto_rate": round(a["completed"] / p, 3),
            "escalation_rate": round(a["escalated"] / p, 3),
            "avg_confidence": round(a["conf_sum"] / a["conf_n"], 3) if a["conf_n"] else None,
            "avg_duration_ms": round(a["dur_sum"] / a["dur_n"]) if a["dur_n"] else None,
            "error_codes": dict(a["errors"]),
        })
    totals = {
        "window_days": days,
        "processed": sum(x["processed"] for x in agents),
        "completed": sum(x["completed"] for x in agents),
        "escalated": sum(x["escalated"] for x in agents),
        "failed": sum(x["failed"] for x in agents),
        "agents_active": len(agents),
    }
    return {"totals": totals, "agents": agents}
