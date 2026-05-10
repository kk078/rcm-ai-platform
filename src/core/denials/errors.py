"""
Domain-specific exceptions for denial management and appeal generation.

Each exception carries an HTTP status code and human-readable detail
so the route layer can map them to FastAPI HTTPException responses.
"""


class DenialError(Exception):
    """Base exception for denial management errors."""

    def __init__(self, detail: str, status_code: int = 400):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


class DenialNotFoundError(DenialError):
    def __init__(self, denial_id=None):
        msg = f"Denial {denial_id} not found" if denial_id else "Denial not found"
        super().__init__(msg, status_code=404)


class DenialStatusError(DenialError):
    def __init__(self, detail: str = "Invalid denial status transition"):
        super().__init__(detail, status_code=422)


class AppealNotFoundError(DenialError):
    def __init__(self, appeal_id=None):
        msg = f"Appeal {appeal_id} not found" if appeal_id else "Appeal not found"
        super().__init__(msg, status_code=404)


class DenialClassificationError(DenialError):
    def __init__(self, detail: str = "Denial classification failed"):
        super().__init__(detail, status_code=422)