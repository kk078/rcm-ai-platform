"""
Error Intelligence API — staff-only endpoints for the AI debugging dashboard.

GET  /api/v1/errors/              — paginated list with filters
GET  /api/v1/errors/{id}          — full detail with AI analysis
PATCH /api/v1/errors/{id}/resolve — mark as resolved
POST /api/v1/errors/{id}/reanalyze — re-run AI analysis
POST /api/v1/errors/{id}/apply-fix — manually trigger auto-patcher
GET  /api/v1/errors/stats         — summary counts by severity / status
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
import asyncpg
import json
import structlog

from src.config import get_settings
from src.infrastructure.auth.middleware import get_current_user

logger = structlog.get_logger()
router = APIRouter()
settings = get_settings()


# ── Helpers ────────────────────────────────────────────────────────────────

async def _get_conn():
    db_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    return await asyncpg.connect(db_url)


# ── Schemas ────────────────────────────────────────────────────────────────

class ErrorLogSummary(BaseModel):
    id: str
    error_type: str
    message: str
    request_path: Optional[str]
    request_method: Optional[str]
    status_code: Optional[int]
    severity: str
    analysis_status: str    # analyzing | complete | failed
    resolved: bool
    occurrence_count: int
    created_at: datetime
    affected_area: Optional[str] = None
    root_cause: Optional[str] = None
    patch_applied: bool = False
    patch_applied_at: Optional[datetime] = None


class ErrorLogDetail(ErrorLogSummary):
    stack_trace: str
    user_id: Optional[str]
    sentry_event_id: Optional[str]
    ai_analysis: Optional[dict]
    resolved_at: Optional[datetime]
    patch_backup_path: Optional[str] = None
    patch_diff: Optional[str] = None
    patch_error: Optional[str] = None


class ErrorStats(BaseModel):
    total: int
    unresolved: int
    critical: int
    high: int
    medium: int
    low: int
    last_24h: int
    security_related: int
    auto_patched: int = 0


class ResolveRequest(BaseModel):
    notes: Optional[str] = None


class ApplyFixResponse(BaseModel):
    status: str          # patched | failed | dry_run
    error_id: str
    file_patched: Optional[str] = None
    backup_path: Optional[str] = None
    error: Optional[str] = None
    dry_run: bool = False


# ── Routes ─────────────────────────────────────────────────────────────────

@router.get("/stats", response_model=ErrorStats, summary="Error summary statistics")
async def get_error_stats(current_user=Depends(get_current_user)):
    """Overall counts for the dashboard header cards."""
    _require_staff(current_user)
    try:
        conn = await _get_conn()
        try:
            row = await conn.fetchrow("""
                SELECT
                    COUNT(*)::int                                        AS total,
                    COUNT(*) FILTER (WHERE NOT resolved)::int           AS unresolved,
                    COUNT(*) FILTER (WHERE severity='critical')::int    AS critical,
                    COUNT(*) FILTER (WHERE severity='high')::int        AS high,
                    COUNT(*) FILTER (WHERE severity='medium')::int      AS medium,
                    COUNT(*) FILTER (WHERE severity='low')::int         AS low,
                    COUNT(*) FILTER (
                        WHERE created_at >= now() - interval '24 hours'
                    )::int                                               AS last_24h,
                    COUNT(*) FILTER (
                        WHERE ai_analysis->>'is_security_related' = 'true'
                        AND NOT resolved
                    )::int                                               AS security_related,
                    COUNT(*) FILTER (
                        WHERE patch_applied = true
                    )::int                                               AS auto_patched
                FROM error_logs
            """)
            if row:
                return ErrorStats(**dict(row))
        finally:
            await conn.close()
    except Exception as e:
        logger.warning("error_logs query failed", error=str(e))
    return ErrorStats(
        total=0, unresolved=0, critical=0, high=0, medium=0,
        low=0, last_24h=0, security_related=0, auto_patched=0,
    )


@router.get("", response_model=list[ErrorLogSummary], summary="List errors")
async def list_errors(
    severity: Optional[str] = Query(None, description="critical|high|medium|low"),
    resolved: Optional[bool] = Query(None),
    analysis_status: Optional[str] = Query(None, description="analyzing|complete|failed"),
    patch_applied: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user=Depends(get_current_user),
):
    _require_staff(current_user)
    try:
        conn = await _get_conn()
        try:
            conditions = []
            params = []
            i = 1

            if severity:
                conditions.append(f"severity = ${i}")
                params.append(severity)
                i += 1
            if resolved is not None:
                conditions.append(f"resolved = ${i}")
                params.append(resolved)
                i += 1
            if analysis_status:
                conditions.append(f"analysis_status = ${i}")
                params.append(analysis_status)
                i += 1
            if patch_applied is not None:
                conditions.append(f"patch_applied = ${i}")
                params.append(patch_applied)
                i += 1

            where = "WHERE " + " AND ".join(conditions) if conditions else ""
            params.extend([limit, offset])

            rows = await conn.fetch(f"""
                SELECT
                    id::text, error_type, message, request_path, request_method,
                    status_code, severity, analysis_status, resolved, occurrence_count,
                    created_at,
                    ai_analysis->>'affected_area'  AS affected_area,
                    ai_analysis->>'root_cause'     AS root_cause,
                    COALESCE(patch_applied, false)  AS patch_applied,
                    patch_applied_at
                FROM error_logs
                {where}
                ORDER BY
                    CASE severity
                        WHEN 'critical' THEN 1
                        WHEN 'high'     THEN 2
                        WHEN 'medium'   THEN 3
                        ELSE 4
                    END,
                    created_at DESC
                LIMIT ${i} OFFSET ${i+1}
            """, *params)

            return [ErrorLogSummary(**dict(r)) for r in rows]
        finally:
            await conn.close()
    except Exception as e:
        logger.warning("list_errors query failed", error=str(e))
        return []


@router.get("/{error_id}", response_model=ErrorLogDetail, summary="Get error detail")
async def get_error(error_id: str, current_user=Depends(get_current_user)):
    _require_staff(current_user)
    conn = await _get_conn()
    try:
        row = await conn.fetchrow("""
            SELECT
                id::text, error_type, message, stack_trace,
                request_path, request_method, status_code,
                user_id::text, sentry_event_id, severity,
                analysis_status, ai_analysis, resolved, occurrence_count,
                created_at, resolved_at,
                COALESCE(patch_applied, false) AS patch_applied,
                patch_applied_at, patch_backup_path, patch_diff, patch_error
            FROM error_logs WHERE id = $1::uuid
        """, error_id)

        if not row:
            raise HTTPException(status_code=404, detail="Error log not found")

        data = dict(row)
        if data.get("ai_analysis") and isinstance(data["ai_analysis"], str):
            data["ai_analysis"] = json.loads(data["ai_analysis"])

        return ErrorLogDetail(**data)
    finally:
        await conn.close()


@router.patch("/{error_id}/resolve", summary="Mark error as resolved")
async def resolve_error(
    error_id: str,
    body: ResolveRequest,
    current_user=Depends(get_current_user),
):
    _require_staff(current_user)
    conn = await _get_conn()
    try:
        result = await conn.execute("""
            UPDATE error_logs
            SET resolved = true,
                resolved_at = now(),
                resolved_by = $2::uuid,
                updated_at = now()
            WHERE id = $1::uuid
        """, error_id, str(current_user["user_id"]))

        if result == "UPDATE 0":
            raise HTTPException(status_code=404, detail="Error log not found")

        return {"status": "resolved", "error_id": error_id}
    finally:
        await conn.close()


@router.post("/{error_id}/reanalyze", summary="Re-run AI analysis on this error")
async def reanalyze_error(error_id: str, current_user=Depends(get_current_user)):
    _require_staff(current_user)
    conn = await _get_conn()
    try:
        row = await conn.fetchrow("""
            SELECT id::text, error_type, message, stack_trace,
                   request_path, request_method, status_code, user_id::text
            FROM error_logs WHERE id = $1::uuid
        """, error_id)

        if not row:
            raise HTTPException(status_code=404, detail="Error log not found")

        # Reset status and re-queue
        await conn.execute("""
            UPDATE error_logs SET analysis_status = 'analyzing', updated_at = now()
            WHERE id = $1::uuid
        """, error_id)

        data = dict(row)
        from src.core.error_intelligence.tasks import record_and_analyze_error
        record_and_analyze_error.delay(
            error_log_id=data["id"],
            error_type=data["error_type"],
            message=data["message"],
            stack_trace=data["stack_trace"],
            request_path=data.get("request_path"),
            request_method=data.get("request_method"),
            status_code=data.get("status_code"),
            user_id=data.get("user_id"),
        )

        return {"status": "reanalyzing", "error_id": error_id}
    finally:
        await conn.close()


@router.post(
    "/{error_id}/apply-fix",
    response_model=ApplyFixResponse,
    summary="Manually trigger AI auto-patcher on this error",
)
async def apply_fix(
    error_id: str,
    dry_run: bool = Query(False, description="If true, generate the diff but do NOT write to disk"),
    current_user=Depends(get_current_user),
):
    """
    Trigger the auto-patcher for a specific error. Useful for errors that were
    skipped at analysis time (e.g. security-flagged or low-confidence) or for
    manually re-applying a patch after a rollback.
    """
    _require_staff(current_user)
    conn = await _get_conn()
    try:
        row = await conn.fetchrow("""
            SELECT id::text, error_type, message, stack_trace,
                   ai_analysis, severity
            FROM error_logs WHERE id = $1::uuid
        """, error_id)

        if not row:
            raise HTTPException(status_code=404, detail="Error log not found")

        data = dict(row)
        ai_analysis = data.get("ai_analysis") or {}
        if isinstance(ai_analysis, str):
            ai_analysis = json.loads(ai_analysis)

        suggested_fix = ai_analysis.get("suggested_fix", "Review the stack trace")
        root_cause = ai_analysis.get("root_cause", "Unknown root cause")
        confidence = ai_analysis.get("confidence", "medium")

        # Run patcher synchronously in this request (it's a staff-only action,
        # latency is acceptable; avoids extra Celery round-trip for manual triggers)
        import asyncio
        import concurrent.futures
        loop = asyncio.get_event_loop()

        from src.core.error_intelligence.patcher import auto_patch
        with concurrent.futures.ThreadPoolExecutor() as pool:
            patch_result = await loop.run_in_executor(
                pool,
                lambda: auto_patch(
                    error_type=data["error_type"],
                    message=data["message"],
                    stack_trace=data.get("stack_trace", ""),
                    suggested_fix=suggested_fix,
                    root_cause=root_cause,
                    confidence=confidence,
                    dry_run=dry_run,
                ),
            )

        if not dry_run:
            await conn.execute("""
                UPDATE error_logs SET
                    patch_applied     = $2,
                    patch_backup_path = $3,
                    patch_diff        = $4,
                    patch_applied_at  = CASE WHEN $2 THEN now() ELSE NULL END,
                    patch_error       = $5,
                    updated_at        = now()
                WHERE id = $1::uuid
            """,
                error_id,
                patch_result.success,
                patch_result.backup_path,
                patch_result.diff_applied,
                patch_result.error,
            )

        status = "dry_run" if dry_run else ("patched" if patch_result.success else "failed")

        logger.info(
            "manual_apply_fix",
            error_id=error_id,
            status=status,
            file_patched=patch_result.file_patched,
            triggered_by=str(current_user.get("user_id", "unknown")),
        )

        return ApplyFixResponse(
            status=status,
            error_id=error_id,
            file_patched=patch_result.file_patched,
            backup_path=patch_result.backup_path,
            error=patch_result.error,
            dry_run=dry_run,
        )
    finally:
        await conn.close()


# ── Frontend capture endpoint ─────────────────────────────────────────────

class CaptureRequest(BaseModel):
    error_type: str
    message: str
    stack_trace: str = ""
    url: Optional[str] = None        # window.location.pathname where error occurred
    component_stack: Optional[str] = None  # React component stack (if applicable)
    source: str = "frontend"         # frontend | agent | extension


@router.post("/capture", summary="Capture a frontend JS error for AI analysis")
async def capture_frontend_error(
    body: CaptureRequest,
    current_user=Depends(get_current_user),
):
    """
    Ingest a JavaScript error (window.onerror / unhandledrejection) from the
    staff portal and queue it for AI analysis.

    HIPAA note: callers MUST sanitize PHI before sending.  This endpoint
    accepts the payload as-is and trusts the frontend to have scrubbed
    sensitive fields (passwords, SSNs, DOBs, MRNs, etc.).
    """
    conn = await _get_conn()
    try:
        uid: Optional[str] = str(current_user.get("user_id", "")) or None

        row = await conn.fetchrow(
            """
            INSERT INTO error_logs (
                error_type, message, stack_trace,
                request_path, request_method,
                severity, analysis_status,
                user_id, occurrence_count
            ) VALUES (
                $1, $2, $3,
                $4, 'GET',
                'medium', 'analyzing',
                $5::uuid, 1
            )
            RETURNING id::text
            """,
            (body.error_type or "JavaScriptError")[:200],
            (body.message or "")[:2000],
            (body.stack_trace or "")[:8000],
            (body.url or "")[:500] or None,
            uid,
        )

        if row:
            error_log_id = row["id"]
            from src.core.error_intelligence.tasks import record_and_analyze_error
            record_and_analyze_error.delay(
                error_log_id=error_log_id,
                error_type=body.error_type,
                message=body.message,
                stack_trace=body.stack_trace,
                request_path=body.url,
                request_method="GET",
                status_code=None,
                user_id=uid,
            )
            logger.info(
                "frontend_error_captured",
                error_log_id=error_log_id,
                error_type=body.error_type,
                source=body.source,
            )

        return {"status": "captured"}

    except Exception as exc:
        # Never surface capture failures to the client — an error in the error
        # capture path must not break the UI.
        logger.warning("frontend_capture_failed", error=str(exc))
        return {"status": "captured"}
    finally:
        await conn.close()


# ── Auth helper ──────────────────────────────────────────────────────────

def _require_staff(user: dict):
    """Only internal (staff) users can access the Error Intelligence dashboard."""
    if user.get("user_type") != "internal":
        raise HTTPException(
            status_code=403,
            detail="Error Intelligence dashboard is restricted to internal staff.",
        )
