"""NPPES (NPI Registry) + CMS/payer enrichment.

NPPES is the free public CMS NPI Registry API:
  https://npiregistry.cms.hhs.gov/api/?version=2.1
We use it to fill provider NPI, taxonomy, credential, and practice address that
the clinical note never contains. Results are cached in-process to avoid
hammering the API for repeat lookups within a session.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

NPPES_URL = "https://npiregistry.cms.hhs.gov/api/"
_cache: dict[str, Optional[dict]] = {}


def _first_address(rec: dict, purpose: str = "LOCATION") -> dict:
    addrs = rec.get("addresses") or []
    for a in addrs:
        if a.get("address_purpose") == purpose:
            return a
    return addrs[0] if addrs else {}


def _shape(rec: dict) -> dict:
    """Normalise an NPPES record into the fields the form mappers need."""
    basic = rec.get("basic") or {}
    taxes = rec.get("taxonomies") or []
    primary_tax = next((t for t in taxes if t.get("primary")), taxes[0] if taxes else {})
    addr = _first_address(rec, "LOCATION")
    zip_ = (addr.get("postal_code") or "").replace("-", "")
    return {
        "npi": rec.get("number"),
        "enumeration_type": rec.get("enumeration_type"),  # NPI-1 (individual) / NPI-2 (org)
        "first_name": basic.get("first_name"),
        "last_name": basic.get("last_name"),
        "organization_name": basic.get("organization_name") or basic.get("name"),
        "credential": basic.get("credential"),
        "sex": basic.get("sex"),
        "taxonomy_code": primary_tax.get("code"),
        "taxonomy_desc": primary_tax.get("desc"),
        "license": primary_tax.get("license"),
        "address_1": addr.get("address_1"),
        "address_2": addr.get("address_2"),
        "city": addr.get("city"),
        "state": addr.get("state"),
        "zip": zip_,
        "phone": addr.get("telephone_number"),
        "fax": addr.get("fax_number"),
        "source": "NPPES",
    }


async def _query(params: dict[str, Any]) -> Optional[dict]:
    key = "|".join(f"{k}={v}" for k, v in sorted(params.items()))
    if key in _cache:
        return _cache[key]
    params = {"version": "2.1", "limit": 5, **params}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(NPPES_URL, params=params)
            r.raise_for_status()
            data = r.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("nppes: lookup failed params=%s err=%s", params, exc)
        _cache[key] = None
        return None
    results = data.get("results") or []
    shaped = _shape(results[0]) if results else None
    _cache[key] = shaped
    return shaped


async def lookup_npi(npi: str) -> Optional[dict]:
    """Look up a single NPI number."""
    if not npi:
        return None
    return await _query({"number": str(npi).strip()})


async def lookup_individual(first_name: str, last_name: str, state: str | None = None) -> Optional[dict]:
    """Look up an individual provider (NPI-1) by name (+ optional state)."""
    if not (first_name and last_name):
        return None
    p = {"first_name": first_name.strip(), "last_name": last_name.strip(), "enumeration_type": "NPI-1"}
    if state:
        p["state"] = state.strip()
    return await _query(p)


async def lookup_organization(org_name: str, state: str | None = None) -> Optional[dict]:
    """Look up an organization (NPI-2) by name (+ optional state)."""
    if not org_name:
        return None
    p = {"organization_name": org_name.strip(), "enumeration_type": "NPI-2"}
    if state:
        p["state"] = state.strip()
    return await _query(p)


# ── CMS / payer resolution ───────────────────────────────────────────────────
# Minimal payer-id map for the payers seen in real notes; falls back to the
# name on file. (A full clearinghouse payer list can replace this dict later.)
_PAYER_MAP: dict[str, dict] = {
    "SMFL0":  {"name": "Medicare Part B (Florida / First Coast)", "type": "Medicare", "claim_filing": "MB"},
    "MR":     {"name": "Medicare", "type": "Medicare", "claim_filing": "MB"},
    "62308":  {"name": "Cigna", "type": "Commercial", "claim_filing": "CI"},
    "00590":  {"name": "Cigna", "type": "Commercial", "claim_filing": "CI"},
    "60054":  {"name": "Aetna", "type": "Commercial", "claim_filing": "CI"},
    "00060":  {"name": "Florida Blue (BCBS FL)", "type": "Commercial", "claim_filing": "BL"},
}


def resolve_payer(payer_id_number: str | None, payer_name: str | None = None) -> dict:
    """Resolve a payer id to a normalized name/type/claim-filing-indicator."""
    pid = (payer_id_number or "").strip().upper()
    if pid in _PAYER_MAP:
        out = dict(_PAYER_MAP[pid]); out["payer_id"] = pid; out["source"] = "CMS/payer-map"
        return out
    # Heuristic on name
    name = (payer_name or "").strip()
    low = name.lower()
    if "medicare" in low:
        cf = "MB"; typ = "Medicare"
    elif "medicaid" in low:
        cf = "MC"; typ = "Medicaid"
    else:
        cf = "CI"; typ = "Commercial"
    return {"name": name or "Unknown payer", "type": typ, "claim_filing": cf,
            "payer_id": pid or None, "source": "name-heuristic"}
