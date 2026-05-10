"""
Domain-specific exceptions for coding operations.

Each exception carries an HTTP status code and human-readable detail
so the route layer can map them to FastAPI HTTPException responses.
"""


class CodingError(Exception):
    """Base exception for coding errors."""

    def __init__(self, detail: str, status_code: int = 400):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


class CodingSessionNotFoundError(CodingError):
    def __init__(self, session_id=None):
        msg = f"Coding session {session_id} not found" if session_id else "Coding session not found"
        super().__init__(msg, status_code=404)


class EncounterNotFoundError(CodingError):
    def __init__(self, encounter_id=None):
        msg = f"Encounter {encounter_id} not found" if encounter_id else "Encounter not found"
        super().__init__(msg, status_code=404)


class CodingSessionAlreadyApprovedError(CodingError):
    def __init__(self, session_id=None):
        msg = f"Coding session {session_id} has already been approved" if session_id else "Coding session already approved"
        super().__init__(msg, status_code=409)


class AIServiceUnavailableError(CodingError):
    def __init__(self, detail: str = "AI coding service is currently unavailable"):
        super().__init__(detail, status_code=503)


class CodeValidationFailedError(CodingError):
    def __init__(self, detail: str = "Code validation failed", errors: dict | None = None):
        self.errors = errors or {}
        super().__init__(detail, status_code=422)


class DocumentExtractionError(CodingError):
    def __init__(self, detail: str = "Failed to extract text from document"):
        super().__init__(detail, status_code=422)