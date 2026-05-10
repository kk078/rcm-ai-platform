"""
Domain-specific exceptions for the provider portal.

Each exception carries an HTTP status code and human-readable detail
so the route layer can map them to FastAPI HTTPException responses.
"""


class PortalError(Exception):
    """Base exception for provider portal errors."""

    def __init__(self, detail: str, status_code: int = 400):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


class MessageNotFoundError(PortalError):
    def __init__(self, message_id=None):
        msg = f"Message {message_id} not found" if message_id else "Message not found"
        super().__init__(msg, status_code=404)


class NotificationNotFoundError(PortalError):
    def __init__(self, notification_id=None):
        msg = f"Notification {notification_id} not found" if notification_id else "Notification not found"
        super().__init__(msg, status_code=404)


class ClaimAccessError(PortalError):
    def __init__(self, detail: str = "Claim does not belong to your practice"):
        super().__init__(detail, status_code=403)


class PortalReportError(PortalError):
    def __init__(self, detail: str = "Unable to generate report"):
        super().__init__(detail, status_code=422)