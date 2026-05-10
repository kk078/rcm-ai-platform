"""Payment posting domain: ERA/835 parsing, matching, auto-posting, underpayment detection."""

from src.core.payments.errors import (
    PaymentError,
    BatchNotFoundError,
    PaymentLineNotFoundError,
    ERAParseError,
    BatchStatusError,
    ClaimMatchError,
    UnderpaymentDisputeError,
)
from src.core.payments.service import PaymentService, payment_service

__all__ = [
    "PaymentError",
    "BatchNotFoundError",
    "PaymentLineNotFoundError",
    "ERAParseError",
    "BatchStatusError",
    "ClaimMatchError",
    "UnderpaymentDisputeError",
    "PaymentService",
    "payment_service",
]