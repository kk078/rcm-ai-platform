"""
Celery task: record an error to the DB and run AI analysis on it.
Uses asyncio.run() to bridge Celery's sync world and asyncpg's async DB.
After analysis, automatically applies a code patch for critical/high severity errors.
"""

import asyncio
import os
import uuid
import json
import structlog
from typing import Optional
from celery import shared_task

from src.infrastructure.queue.celery_app import celery_app

logger = structlog.get_logger()

# Severities that trigger automatic patching
_AUTO_PATCH_SEVERITIES = {"critical", "high"}


@celery_app.task(
    name="src.core.error_intelligence.tasks.record_and_analyze_error",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    queue="default",
)
def record_and_analyze_error(
    self,
    error_log_id: str,
    error_type: str,
    message: str,
    stack_trace: str,
    request_path: Optional[str] = None,
    request_method: Optional[str] = None,
    status_code: Optional[int] = None,
    user_id: Optional[str] = None,
    sentry_event_id: Optional[str] = None,
):
    """
    1. Insert a new error_logs row with status='analyzing'.
    2. Call the AI analyzer.
    3. Update the row with the analysis result.
    4. For critical/high errors, attempt automatic code patching.
    """
    try:
        asyncio.run(_async_record_and_analyze(
            error_log_id=error_log_id,
            error_type=error_type,
            message=message,
            stack_trace=stack_trace,
            request_path=request_path,
            request_method=request_method,
            status_code=status_code,
            user_id=user_id,
            sentry_event_id=sentry_event_id,
        ))
    except Exception as exc:
        logger.error("record_and_analyze_error_task_failed", error=str(exc), error_log_id=error_log_id)
        try:
            self.retry(exc=exc)
        except Exception:
            pass


async def _async_record_and_analyze(
    error_log_id: str,
    error_type: str,
    message: str,
    stack_trace: str,
    request_path: Optional[str],
    request_method: Optional[str],
    status_code: Optional[int],
    user_id: Optional[str],
    sentry_event_id: Optional[str],
):
    import asyncpg
    from src.config import get_settings
    settings = get_settings()

    # Parse DATABASE_URL for asyncpg (strip +asyncpg driver prefix)
    db_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")

    conn = await asyncpg.connect(db_url)
    try:
        # Step 1 — insert with status 'analyzing'
        await conn.execute(
            """
            INSERT INTO error_logs (
                id, error_type, message, stack_trace,
                request_path, request_method, status_code,
                user_id, sentry_event_id, analysis_status,
                severity, created_at, updated_at
            ) VALUES (
                $1::uuid, $2, $3, $4,
                $5, $6, $7,
                $8::uuid, $9, 'analyzing',
                'unknown', now(), now()
            )
            ON CONFLICT (id) DO NOTHING
            """,
            error_log_id,
            error_type,
            message[:2000],
            stack_trace[:10000],
            request_path,
            request_method,
            status_code,
            user_id if user_id else None,
            sentry_event_id,
        )

        # Step 2 — AI analysis (synchronous call, runs in this async context via thread)
        from src.core.error_intelligence.analyzer import analyze_error
        import concurrent.futures
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            analysis = await loop.run_in_executor(
                pool,
                lambda: analyze_error(
                    error_type=error_type,
                    message=message,
                    stack_trace=stack_trace,
                    request_path=request_path,
                    request_method=request_method,
                    status_code=status_code,
                    user_id=user_id,
                ),
            )

        # Step 3 — update with analysis result
        await conn.execute(
            """
            UPDATE error_logs SET
                severity = $2,
                ai_analysis = $3,
                analysis_status = 'complete',
                updated_at = now()
            WHERE id = $1::uuid
            """,
            error_log_id,
            analysis.severity,
            json.dumps(analysis.to_dict()),
        )

        logger.info(
            "error_intelligence_complete",
            error_log_id=error_log_id,
            severity=analysis.severity,
            is_security=analysis.is_security_related,
        )

        # Step 4 — Auto-patch for critical/high severity (skip security-related)
        # Security-related errors should be reviewed by a human before patching
        should_patch = (
            analysis.severity in _AUTO_PATCH_SEVERITIES
            and not analysis.is_security_related
            and analysis.confidence in ("high", "medium")
        )

        if should_patch:
            logger.info(
                "auto_patch_triggered",
                error_log_id=error_log_id,
                severity=analysis.severity,
                confidence=analysis.confidence,
            )
            with concurrent.futures.ThreadPoolExecutor() as pool:
                patch_result = await loop.run_in_executor(
                    pool,
                    lambda: _run_patcher(
                        error_type=error_type,
                        message=message,
                        stack_trace=stack_trace,
                        suggested_fix=analysis.suggested_fix,
                        root_cause=analysis.root_cause,
                        confidence=analysis.confidence,
                    ),
                )

            # Step 5 — persist patch result
            await conn.execute(
                """
                UPDATE error_logs SET
                    patch_applied        = $2,
                    patch_backup_path    = $3,
                    patch_diff           = $4,
                    patch_applied_at     = CASE WHEN $2 THEN now() ELSE NULL END,
                    patch_error          = $5,
                    updated_at           = now()
                WHERE id = $1::uuid
                """,
                error_log_id,
                patch_result.success,
                patch_result.backup_path,
                patch_result.diff_applied,
                patch_result.error,
            )

            logger.info(
                "auto_patch_result_saved",
                error_log_id=error_log_id,
                success=patch_result.success,
                file_patched=patch_result.file_patched,
                error=patch_result.error,
            )

    finally:
        await conn.close()


def _run_patcher(
    error_type: str,
    message: str,
    stack_trace: str,
    suggested_fix: str,
    root_cause: str,
    confidence: str,
) -> "PatchResult":
    """
    Synchronous wrapper for the auto-patcher — safe to call from a ThreadPoolExecutor.
    Returns a PatchResult (never raises).
    """
    try:
        from src.core.error_intelligence.patcher import auto_patch, PatchResult
        return auto_patch(
            error_type=error_type,
            message=message,
            stack_trace=stack_trace,
            suggested_fix=suggested_fix,
            root_cause=root_cause,
            confidence=confidence,
            dry_run=False,
        )
    except Exception as exc:
        logger.error("run_patcher_failed", error=str(exc))
        from src.core.error_intelligence.patcher import PatchResult
        return PatchResult(success=False, error=str(exc)[:300])
