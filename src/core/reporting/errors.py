"""
Domain-specific exceptions for analytics and reporting.

Each exception carries an HTTP status code and human-readable detail
so the route layer can map them to FastAPI HTTPException responses.
"""


class AnalyticsError(Exception):
    """Base exception for analytics and reporting errors."""

    def __init__(self, detail: str, status_code: int = 400):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


class ReportGenerationError(AnalyticsError):
    def __init__(self, detail: str = "Unable to generate report"):
        super().__init__(detail, status_code=422)