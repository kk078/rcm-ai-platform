"""
Domain-specific exceptions for payment posting and ERA processing.

Each exception carries an HTTP status code and human-readable detail
so the route layer can map them to FastAPI HTTPException responses.
"""


class PaymentError(Exception):
    """Base exception for payment/ERA errors."""

    def __init__(self, detail: str, status_code: int = 400):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


class BatchNotFoundError(PaymentError):
    def __init__(self, batch_id=None):
        msg = f"Payment batch {batch_id} not found" if batch_id else "Payment batch not found"
        super().__init__(msg, status_code=404)


class PaymentLineNotFoundError(PaymentError):
    def __init__(self, line_id=None):
        msg = f"Payment line {line_id} not found" if line_id else "Payment line not found"
        super().__init__(msg, status_code=404)


class ERAParseError(PaymentError):
    def __init__(self, detail: str = "Failed to parse ERA/835 file"):
        super().__init__(detail, status_code=422)


class BatchStatusError(PaymentError):
    def __init__(self, detail: str = "Invalid batch status transition"):
        super().__init__(detail, status_code=422)


class ClaimMatchError(PaymentError):
    def __init__(self, detail: str = "Claim matching failed"):
        super().__init__(detail, status_code=422)


class UnderpaymentDisputeError(PaymentError):
    def __init__(self, detail: str = "Underpayment dispute error"):
        super().__init__(detail, status_code=400)