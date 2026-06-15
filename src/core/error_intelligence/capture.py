"""
Error capture — saves an ErrorLog record and enqueues the AI analysis task.
Called from the FastAPI global exception handler so every unhandled 5xx is recorded.
"""

import traceback
import uuid
import structlog
from typing import Optional
from fastapi import Request

logger = structlog.get_logger()


def capture_error(
    exc: Exception,
    request: Optional[Request] = None,
    status_code: int = 500,
    sentry_event_id: Optional[str] = None,
) -> Optional[str]:
    """
    Persist an ErrorLog row and fire the AI analysis Celery task.
    Returns the error_log_id (str UUID) so the response can include it.
    Non-blocking — any DB/Celery failure is swallowed to never affect the response.
    """
    try:
        error_log_id = str(uuid.uuid4())
        error_type = type(exc).__name__
        message = str(exc)
        stack = traceback.format_exc()

        request_path = None
        request_method = None
        user_id = None

        if request:
            request_path = str(request.url.path)
            request_method = request.method
            user_id = str(getattr(request.state, "user_id", None) or "")

        # Fire-and-forget Celery task — import here to avoid circular imports
        from src.core.error_intelligence.tasks import record_and_analyze_error
        record_and_analyze_error.delay(
            error_log_id=error_log_id,
            error_type=error_type,
            message=message,
            stack_trace=stack,
            request_path=request_path,
            request_method=request_method,
            status_code=status_code,
            user_id=user_id or None,
            sentry_event_id=sentry_event_id,
        )

        logger.info(
            "error_captured",
            error_log_id=error_log_id,
            error_type=error_type,
            path=request_path,
        )
        return error_log_id

    except Exception as capture_exc:
        # Never let the capture system crash the main request handler
        logger.warning("error_capture_failed", reason=str(capture_exc))
        return None
