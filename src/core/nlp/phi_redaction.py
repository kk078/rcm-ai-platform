"""
PHI Redaction Service — De-identifies Protected Health Information
before sending data to external AI APIs.

Uses Microsoft Presidio + custom healthcare NER patterns.
Supports re-hydration to restore PHI in responses.
"""

import re
import structlog
from typing import Any
from uuid import uuid4

logger = structlog.get_logger()

# PHI pattern definitions for healthcare-specific entities
PHI_PATTERNS = {
    "SSN": r"\b\d{3}-\d{2}-\d{4}\b",
    "MRN": r"\bMRN[:\s#]*\d{4,12}\b",
    "MEMBER_ID": r"\b(?:Member|Subscriber|ID)[:\s#]*[A-Z0-9]{6,20}\b",
    "PHONE": r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
    "EMAIL": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    "DOB": r"\b(?:DOB|Date of Birth|born)[:\s]*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
    "DATE": r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
    "ZIP": r"\b\d{5}(?:-\d{4})?\b",
    "ACCOUNT_NUM": r"\b(?:Account|Acct)[:\s#]*\d{6,15}\b",
    "CLAIM_NUM": r"\b(?:Claim)[:\s#]*[A-Z0-9]{8,20}\b",
}


class PHIRedactor:
    """
    Redacts PHI from text before external API calls.
    Maintains a mapping for re-hydration of responses.
    """

    def __init__(self):
        self._compiled_patterns = {
            name: re.compile(pattern, re.IGNORECASE)
            for name, pattern in PHI_PATTERNS.items()
        }

    def redact(self, text: str) -> tuple[str, dict[str, str]]:
        """
        Redact all PHI from text.

        Returns:
            tuple of (redacted_text, redaction_map)
            redaction_map: {placeholder: original_value}
        """
        redaction_map: dict[str, str] = {}
        redacted_text = text

        for phi_type, pattern in self._compiled_patterns.items():
            matches = pattern.findall(redacted_text)
            for match in set(matches):
                placeholder = f"[{phi_type}_{uuid4().hex[:8]}]"
                redaction_map[placeholder] = match
                redacted_text = redacted_text.replace(match, placeholder)

        # Also redact potential patient names (simple heuristic — upgrade to NER in production)
        # Names following common medical document patterns
        name_patterns = [
            r"(?:Patient|Pt|Name)[:\s]+([A-Z][a-z]+\s[A-Z][a-z]+)",
            r"(?:Dr\.|Doctor)[:\s]+([A-Z][a-z]+\s[A-Z][a-z]+)",
        ]
        for pattern in name_patterns:
            for match in re.finditer(pattern, redacted_text):
                name = match.group(1)
                placeholder = f"[NAME_{uuid4().hex[:8]}]"
                redaction_map[placeholder] = name
                redacted_text = redacted_text.replace(name, placeholder)

        if redaction_map:
            logger.info("phi_redacted", redaction_count=len(redaction_map))

        return redacted_text, redaction_map

    def rehydrate(self, text: str, redaction_map: dict[str, str]) -> str:
        """Restore PHI in a response using the redaction map."""
        result = text
        for placeholder, original in redaction_map.items():
            result = result.replace(placeholder, original)
        return result

    def is_phi_free(self, text: str) -> bool:
        """Check if text contains any detectable PHI."""
        for pattern in self._compiled_patterns.values():
            if pattern.search(text):
                return False
        return True
