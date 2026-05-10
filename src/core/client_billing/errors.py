"""
Domain-specific exceptions for client billing and invoicing.

Each exception carries an HTTP status code and human-readable detail
so the route layer can map them to FastAPI HTTPException responses.
"""


class InvoiceError(Exception):
    """Base exception for invoice and billing errors."""

    def __init__(self, detail: str, status_code: int = 400):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


class InvoiceNotFoundError(InvoiceError):
    def __init__(self, invoice_id=None):
        msg = f"Invoice {invoice_id} not found" if invoice_id else "Invoice not found"
        super().__init__(msg, status_code=404)


class InvoiceStatusError(InvoiceError):
    def __init__(self, detail: str = "Invalid invoice status transition"):
        super().__init__(detail, status_code=422)


class FeeCalculationError(InvoiceError):
    def __init__(self, detail: str = "Fee calculation failed"):
        super().__init__(detail, status_code=422)