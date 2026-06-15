"""Canonical health-plan-type taxonomy + X12 271 insurance-type-code mapping.

Single source of truth for plan types across the platform. Use `normalize_plan_type`
wherever a plan type is read or written (coverage entry, 270/271 parsing, AI dispatch,
eligibility responses) so the stored value is always one of `PLAN_TYPES` (or None).

Why this exists: `Coverage.plan_type` was a free-text column that ended up holding raw
X12 codes like "MB". This module maps those codes (and common synonyms) to a small,
constrained set of canonical values.
"""
from __future__ import annotations

# ── Canonical plan types (the constrained set) ──────────────────────────────
HMO = "HMO"
PPO = "PPO"
POS = "POS"            # Point of Service (the PLAN type — not CMS Place of Service)
EPO = "EPO"
IPA = "IPA"            # Independent Practice Association (org structure; manual entry only — no X12 code)
INDEMNITY = "Indemnity"
HDHP = "HDHP"
MEDICARE = "Medicare"
MEDICAID = "Medicaid"
OTHER = "Other"

PLAN_TYPES: tuple[str, ...] = (
    HMO, PPO, POS, EPO, IPA, INDEMNITY, HDHP, MEDICARE, MEDICAID, OTHER,
)

# Human-readable labels (handy for UI dropdowns / tooltips).
PLAN_TYPE_LABELS: dict[str, str] = {
    HMO: "HMO (Health Maintenance Organization)",
    PPO: "PPO (Preferred Provider Organization)",
    POS: "POS (Point of Service)",
    EPO: "EPO (Exclusive Provider Organization)",
    IPA: "IPA (Independent Practice Association)",
    INDEMNITY: "Indemnity / Fee-for-Service",
    HDHP: "HDHP (High-Deductible Health Plan)",
    MEDICARE: "Medicare",
    MEDICAID: "Medicaid",
    OTHER: "Other",
}

# ── X12 1336 Insurance Type Code (271 EB04 / SBR05) → canonical plan type ────
# Reference: ASC X12 code list 1336. Covers the codes that actually appear in 270/271
# eligibility responses; anything not listed falls through to synonym/None handling.
X12_INSURANCE_TYPE_CODES: dict[str, str] = {
    "12": PPO,        # Preferred Provider Organization (PPO)
    "13": POS,        # Point of Service (POS)
    "14": EPO,        # Exclusive Provider Organization (EPO)
    "15": INDEMNITY,  # Indemnity Insurance
    "16": HMO,        # HMO Medicare Risk
    "17": OTHER,      # Dental Maintenance Organization
    "HM": HMO,        # Health Maintenance Organization (HMO)
    "HN": HMO,        # HMO - Medicare Risk
    "PR": PPO,        # Preferred Provider Organization (PPO)
    "PS": POS,        # Point of Service (POS)
    "EP": EPO,        # Exclusive Provider Organization (EPO)
    "IN": INDEMNITY,  # Indemnity
    "PP": OTHER,      # Personal Payment (cash - no insurance)
    "OT": OTHER,      # Other
    "MA": MEDICARE,   # Medicare Part A
    "MB": MEDICARE,   # Medicare Part B
    "MP": MEDICARE,   # Medicare Primary
    "CP": MEDICARE,   # Medicare Conditionally Primary
    "MH": MEDICARE,   # Medigap Part A
    "MI": MEDICARE,   # Medigap Part B
    "SP": MEDICARE,   # Supplemental Policy
    "MC": MEDICAID,   # Medicaid
    "QM": MEDICAID,   # Qualified Medicare Beneficiary
    "HS": MEDICAID,   # Special Low Income Medicare Beneficiary
}

# Free-text synonyms (full names, common abbreviations) → canonical.
_SYNONYMS: dict[str, str] = {
    "HEALTH MAINTENANCE ORGANIZATION": HMO,
    "PREFERRED PROVIDER ORGANIZATION": PPO,
    "POINT OF SERVICE": POS,
    "EXCLUSIVE PROVIDER ORGANIZATION": EPO,
    "INDEPENDENT PRACTICE ASSOCIATION": IPA,
    "INDEMNITY INSURANCE": INDEMNITY,
    "FEE FOR SERVICE": INDEMNITY,
    "FFS": INDEMNITY,
    "HIGH DEDUCTIBLE HEALTH PLAN": HDHP,
    "HIGH-DEDUCTIBLE HEALTH PLAN": HDHP,
    "MEDICARE PART A": MEDICARE,
    "MEDICARE PART B": MEDICARE,
    "MEDICARE ADVANTAGE": MEDICARE,
    "MEDIGAP": MEDICARE,
    "MEDICAID MANAGED CARE": MEDICAID,
}

# Fast lookup of canonical values by upper-case form.
_CANONICAL_BY_UPPER: dict[str, str] = {p.upper(): p for p in PLAN_TYPES}


def normalize_plan_type(raw: str | None) -> str | None:
    """Map a raw plan-type string (X12 code, abbreviation, or full name) to a
    canonical value in `PLAN_TYPES`. Returns None for empty input or values that
    cannot be confidently mapped (callers may keep the original if they prefer).

    Examples:
        normalize_plan_type("MB")   -> "Medicare"
        normalize_plan_type("hm")   -> "HMO"
        normalize_plan_type("PPO")  -> "PPO"
        normalize_plan_type("Point of Service") -> "POS"
        normalize_plan_type("")     -> None
        normalize_plan_type("xyz")  -> None
    """
    if raw is None:
        return None
    key = str(raw).strip()
    if not key:
        return None
    upper = key.upper()
    # 1) Already canonical?
    if upper in _CANONICAL_BY_UPPER:
        return _CANONICAL_BY_UPPER[upper]
    # 2) X12 insurance-type code (exact, case-insensitive)?
    if upper in X12_INSURANCE_TYPE_CODES:
        return X12_INSURANCE_TYPE_CODES[upper]
    # 3) Known free-text synonym?
    if upper in _SYNONYMS:
        return _SYNONYMS[upper]
    return None


def is_canonical_plan_type(value: str | None) -> bool:
    """True if value is None or already one of the canonical PLAN_TYPES."""
    return value is None or value in PLAN_TYPES


def validate_plan_type(raw: str | None) -> str | None:
    """Strict variant for API/write boundaries: returns the canonical value, or
    raises ValueError if a non-empty value cannot be mapped. Use in Pydantic
    field validators on coverage-write requests."""
    if raw is None or str(raw).strip() == "":
        return None
    normalized = normalize_plan_type(raw)
    if normalized is None:
        raise ValueError(
            f"Unrecognized plan_type {raw!r}. Expected one of {PLAN_TYPES} "
            f"or a known X12 271 insurance-type code."
        )
    return normalized
