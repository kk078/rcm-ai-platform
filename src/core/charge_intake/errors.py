"""
Domain-specific exceptions for charge intake operations.

Each exception carries an HTTP status code and human-readable detail
so the route layer can map them to FastAPI HTTPException responses.
"""


class ChargeIntakeError(Exception):
    """Base exception for charge intake errors."""

    def __init__(self, detail: str, status_code: int = 400):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


class ChargeNotFoundError(ChargeIntakeError):
    def __init__(self, charge_id=None):
        msg = f"Charge {charge_id} not found" if charge_id else "Charge not found"
        super().__init__(msg, status_code=404)


class ChargeValidationError(ChargeIntakeError):
    def __init__(self, detail: str = "Charge validation failed", errors: dict | None = None):
        self.errors = errors or {}
        super().__init__(detail, status_code=422)


class DuplicateChargeError(ChargeIntakeError):
    def __init__(self, detail: str = "Duplicate charge detected"):
        super().__init__(detail, status_code=409)


class InvalidCSVFormatError(ChargeIntakeError):
    def __init__(self, detail: str = "Invalid CSV format"):
        super().__init__(detail, status_code=422)