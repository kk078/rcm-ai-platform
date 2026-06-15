"""Parser for the X12 271 (Eligibility/Benefit Response, 005010X279A1).

Extracts the fields the platform stores on an EligibilityCheck: coverage status,
plan type (from the EB04 insurance-type code, normalized), plan name, network status,
and the deductible / copay / coinsurance / out-of-pocket amounts carried in EB segments.

Delimiter-aware: reads the element separator and segment terminator from the ISA
control segment when present, and falls back to the X12 defaults (`*` and `~`).
"""
from __future__ import annotations

from .plan_types import normalize_plan_type

# EB01 — Eligibility or Benefit Information Code (subset we act on)
_ACTIVE_CODES = {"1", "2", "3", "4", "5"}   # 1=Active Coverage, etc.
_INACTIVE_CODES = {"6", "7", "8"}           # 6=Inactive, 7=Inactive-Pending Eligibility, 8=Inactive-Pending Investigation


def _delimiters(text: str) -> tuple[str, str]:
    """Return (element_separator, segment_terminator)."""
    if text.startswith("ISA") and len(text) > 105:
        return text[3], text[105]
    # Fall back to defaults; tolerate newline-delimited samples.
    return "*", "~"


def _segments(text: str) -> list[list[str]]:
    elem, seg = _delimiters(text)
    raw = text.replace("\r", "").replace("\n", "")
    out: list[list[str]] = []
    for s in raw.split(seg):
        s = s.strip()
        if s:
            out.append(s.split(elem))
    return out


def _money(val: str | None) -> float | None:
    if not val:
        return None
    try:
        return round(float(val), 2)
    except (ValueError, TypeError):
        return None


def parse_271(text: str) -> dict:
    """Parse a 271 payload into a flat dict aligned to EligibilityCheck fields."""
    result: dict = {
        "status": "unknown",
        "is_active": False,
        "plan_type": None,
        "plan_name": None,
        "network_status": None,
        "deductible_total": None,
        "deductible_met": None,
        "oop_total": None,
        "copay": None,
        "coinsurance_pct": None,
        "payer_name": None,
        "member_id": None,
        "segment_count": 0,
    }
    if not text or not text.strip():
        result["error"] = "empty 271 payload"
        return result

    segs = _segments(text)
    result["segment_count"] = len(segs)
    saw_active = saw_inactive = False

    for el in segs:
        tag = el[0].upper() if el else ""

        if tag == "NM1" and len(el) > 1:
            entity = el[1]
            if entity == "PR" and len(el) > 3:          # Payer
                result["payer_name"] = el[3] or result["payer_name"]
            elif entity == "IL" and len(el) > 9:        # Insured / subscriber
                result["member_id"] = el[9] or result["member_id"]

        elif tag == "EB":
            eb01 = el[1] if len(el) > 1 else ""
            eb04 = el[4] if len(el) > 4 else ""
            eb05 = el[5] if len(el) > 5 else ""
            eb07 = el[7] if len(el) > 7 else ""
            eb08 = el[8] if len(el) > 8 else ""
            eb12 = el[12] if len(el) > 12 else ""

            if eb01 in _ACTIVE_CODES:
                saw_active = True
            elif eb01 in _INACTIVE_CODES:
                saw_inactive = True

            if eb04 and result["plan_type"] is None:
                result["plan_type"] = normalize_plan_type(eb04)
            if eb05 and not result["plan_name"]:
                result["plan_name"] = eb05

            # In-plan-network indicator (EB12: Y=in, N=out)
            if eb12 and result["network_status"] is None:
                if eb12.upper() == "Y":
                    result["network_status"] = "in-network"
                elif eb12.upper() == "N":
                    result["network_status"] = "out-of-network"

            # Monetary / percentage benefits keyed by EB01
            if eb01 == "C" and result["deductible_total"] is None:        # Deductible
                result["deductible_total"] = _money(eb07)
            elif eb01 == "B" and result["copay"] is None:                 # Co-Payment
                result["copay"] = _money(eb07)
            elif eb01 == "G" and result["oop_total"] is None:             # Out of Pocket (Stop Loss)
                result["oop_total"] = _money(eb07)
            elif eb01 == "A" and result["coinsurance_pct"] is None:       # Co-Insurance (percentage in EB08)
                pct = _money(eb08)
                if pct is not None:
                    # 271 carries coinsurance as a decimal fraction (e.g. .20) or whole %.
                    result["coinsurance_pct"] = int(round(pct * 100)) if pct <= 1 else int(round(pct))

    if saw_active:
        result["status"], result["is_active"] = "active", True
    elif saw_inactive:
        result["status"], result["is_active"] = "inactive", False

    return result
