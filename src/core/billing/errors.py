"""
Domain-specific exceptions for billing and claims operations.

Each exception carries an HTTP status code and human-readable detail
so the route layer can map them to FastAPI HTTPException responses.
"""


class BillingError(Exception):
    """Base exception for billing/claims errors."""

    def __init__(self, detail: str, status_code: int = 400):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


class ClaimNotFoundError(BillingError):
    def __init__(self, claim_id=None):
        msg = f"Claim {claim_id} not found" if claim_id else "Claim not found"
        super().__init__(msg, status_code=404)


class ClaimStatusError(BillingError):
    def __init__(self, detail: str = "Invalid claim status transition"):
        super().__init__(detail, status_code=422)


class ClaimScrubError(BillingError):
    def __init__(self, detail: str = "Claim scrubbing failed"):
        super().__init__(detail, status_code=422)


class ClaimSubmissionError(BillingError):
    def __init__(self, detail: str = "Claim submission to clearinghouse failed"):
        super().__init__(detail, status_code=502)