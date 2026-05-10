"""
Domain-specific exceptions for client management operations.

Each exception carries an HTTP status code and human-readable detail
so the route layer can map them to FastAPI HTTPException responses.
"""


class ClientManagementError(Exception):
    """Base exception for client management errors."""

    def __init__(self, detail: str, status_code: int = 400):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


class PracticeNotFoundError(ClientManagementError):
    def __init__(self, practice_id):
        super().__init__(f"Practice {practice_id} not found", status_code=404)


class PracticeAlreadyExistsError(ClientManagementError):
    def __init__(self, detail: str = "Practice already exists"):
        super().__init__(detail, status_code=409)


class OnboardingIncompleteError(ClientManagementError):
    def __init__(self, detail: str = "Onboarding not complete"):
        super().__init__(detail, status_code=422)


class ProviderNotFoundError(ClientManagementError):
    def __init__(self, provider_id=None):
        msg = f"Provider {provider_id} not found" if provider_id else "Provider not found"
        super().__init__(msg, status_code=404)


class PayerEnrollmentConflictError(ClientManagementError):
    def __init__(self, detail: str = "Payer enrollment already exists for this practice"):
        super().__init__(detail, status_code=409)


class PayerNotFoundError(ClientManagementError):
    def __init__(self, payer_id=None):
        msg = f"Payer {payer_id} not found" if payer_id else "Payer not found"
        super().__init__(msg, status_code=404)


class ServiceAgreementConflictError(ClientManagementError):
    def __init__(self, detail: str = "Active service agreement already exists"):
        super().__init__(detail, status_code=409)


class ServiceAgreementNotFoundError(ClientManagementError):
    def __init__(self, practice_id=None):
        msg = f"No active service agreement for practice {practice_id}" if practice_id else "Service agreement not found"
        super().__init__(msg, status_code=404)


class StaffAssignmentConflictError(ClientManagementError):
    def __init__(self, detail: str = "Staff assignment already exists"):
        super().__init__(detail, status_code=409)


class StaffAssignmentNotFoundError(ClientManagementError):
    def __init__(self, assignment_id=None):
        msg = f"Staff assignment {assignment_id} not found" if assignment_id else "Staff assignment not found"
        super().__init__(msg, status_code=404)


class UserNotFoundError(ClientManagementError):
    def __init__(self, user_id=None):
        msg = f"User {user_id} not found" if user_id else "User not found"
        super().__init__(msg, status_code=404)


class UserAlreadyExistsError(ClientManagementError):
    def __init__(self, email: str):
        super().__init__(f"User with email {email} already exists", status_code=409)


class InvalidFeeModelError(ClientManagementError):
    def __init__(self, detail: str = "Invalid fee model configuration"):
        super().__init__(detail, status_code=422)


class PracticeStatusError(ClientManagementError):
    def __init__(self, detail: str = "Invalid practice status transition"):
        super().__init__(detail, status_code=422)