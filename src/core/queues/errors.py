"""
Domain-specific exceptions for work queue management and SLA monitoring.

Each exception carries an HTTP status code and human-readable detail
so the route layer can map them to FastAPI HTTPException responses.
"""


class QueueError(Exception):
    """Base exception for work queue errors."""

    def __init__(self, detail: str, status_code: int = 400):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


class QueueItemNotFoundError(QueueError):
    def __init__(self, item_id=None):
        msg = f"Queue item {item_id} not found" if item_id else "Queue item not found"
        super().__init__(msg, status_code=404)


class QueueItemStatusError(QueueError):
    def __init__(self, detail: str = "Invalid queue item status transition"):
        super().__init__(detail, status_code=422)


class SLABreachError(QueueError):
    def __init__(self, detail: str = "SLA breach detected"):
        super().__init__(detail, status_code=422)