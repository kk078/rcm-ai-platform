"""Assemble a Claim into a CMS-1500 / UB-04 field set, auto-enriching from NPPES + CMS.

Loads the full claim graph (claim, lines, diagnoses, patient, payer, coverage,
encounter, rendering/billing provider, practice), fills the provider NPI /
taxonomy / address from NPPES when missing, resolves the payer, then maps to the
requested form and validates it.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from sqlalchemy import select

from . import nppes
from .forms import build_form, validate_form

logger = logging.getLogger(__name__)
_PTR_TO_LETTER = {str(i): c for i, c in enumerate("ABCDEFGHIJKL", start=1)}


def _d(v) -> str:
    if isinstance(v, date):
        return v.strftime("%m/%d/%Y")
    return str(v) if v else ""


def _money(v) -> str:
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return "0.00"


def _name(last, first) -> str:
    last = (last or "").strip(); first = (first or "").strip()
    if last and first:
        return f"{last}, {first}"
    return last or first or ""


async def assemble_claim_form(db, claim_id: str, form_type: str = "cms1500") -> dict:
    from src.infrastructure.database.models import (  # noqa: PLC0415
        Claim, ClaimLine, ClaimDiagnosis, Patient, Payer, Coverage,
        Encounter, Provider, Practice,
    )

    claim = (await db.execute(select(Claim).where(Claim.id == claim_id))).scalar_one_or_none()
    if claim is None:
        raise ValueError(f"Claim {claim_id} not found")

    async def _by_id(model, _id):
        if not _id:
            return None
        return (await db.execute(select(model).where(model.id == _id))).scalar_one_or_none()

    patient = await _by_id(Patient, claim.patient_id)
    payer = await _by_id(Payer, claim.payer_id)
    coverage = await _by_id(Coverage, claim.coverage_id)
    encounter = await _by_id(Encounter, claim.encounter_id)
    practice = await _by_id(Practice, claim.practice_id)
    rendering = await _by_id(Provider, claim.rendering_provider)
    billing = await _by_id(Provider, claim.billing_provider)

    lines = (await db.execute(
        select(ClaimLine).where(ClaimLine.claim_id == claim.id).order_by(ClaimLine.line_number)
    )).scalars().all()
    dxs = (await db.execute(
        select(ClaimDiagnosis).where(ClaimDiagnosis.claim_id == claim.id).order_by(ClaimDiagnosis.sequence_number)
    )).scalars().all()

    enrichment: dict[str, Any] = {}

    # ── Provider NPI enrichment (NPPES) ──────────────────────────────────────
    rp_state = getattr(practice, "state", None)
    rp_npi = getattr(rendering, "npi", None)
    rp_tax = getattr(rendering, "taxonomy_code", None)
    rp_cred = getattr(rendering, "credential", None)
    if rendering is not None and (not rp_npi or not rp_tax):
        hit = await nppes.lookup_individual(rendering.first_name, rendering.last_name, rp_state)
        if hit:
            rp_npi = rp_npi or hit.get("npi")
            rp_tax = rp_tax or hit.get("taxonomy_code")
            rp_cred = rp_cred or hit.get("credential")
            enrichment["rendering_provider"] = {"npi": hit.get("npi"), "taxonomy": hit.get("taxonomy_code"),
                                                "source": hit.get("source")}

    # ── Billing (group) NPI: practice.group_npi, else NPPES org lookup ───────
    bp_npi = getattr(practice, "group_npi", None)
    if not bp_npi and practice is not None:
        org = await nppes.lookup_organization(getattr(practice, "practice_name", ""), rp_state)
        if org:
            bp_npi = org.get("npi")
            enrichment["billing_provider"] = {"npi": org.get("npi"), "source": org.get("source")}

    # Solo / individual practice fallback: no group NPI -> use the rendering NPI as billing NPI.
    if not bp_npi and rp_npi:
        bp_npi = rp_npi
        enrichment.setdefault("billing_provider", {})
        enrichment["billing_provider"] = {"npi": rp_npi, "source": "rendering-provider-fallback (no group NPI)"}

    payer_resolved = nppes.resolve_payer(
        getattr(payer, "payer_id_number", None), getattr(payer, "payer_name", None))
    enrichment["payer"] = {"name": payer_resolved.get("name"), "source": payer_resolved.get("source")}

    rp_name = _name(getattr(rendering, "last_name", ""), getattr(rendering, "first_name", ""))
    if rp_cred:
        rp_name = f"{rp_name} {rp_cred}".strip()

    # POS from first line / encounter (CMS POS 11 office, 21 inpatient)
    pos = ""
    if lines:
        pos = getattr(lines[0], "place_of_service", "") or ""
    pos = pos or getattr(encounter, "place_of_service", "") or ""

    ctx: dict[str, Any] = {
        "patient": {
            "name": _name(getattr(patient, "last_name", ""), getattr(patient, "first_name", "")),
            "dob": _d(getattr(patient, "date_of_birth", None)),
            "sex": (getattr(patient, "gender", "") or "").upper()[:1],
            "address_1": getattr(patient, "address_line_1", "") or "",
            "address_2": getattr(patient, "address_line_2", "") or "",
            "city": getattr(patient, "city", "") or "",
            "state": getattr(patient, "state", "") or "",
            "zip": getattr(patient, "zip_code", "") or "",
            "phone": getattr(patient, "phone", "") or "",
            "mrn": getattr(patient, "mrn", "") or "",
        },
        "insured": {
            "name": "", "id": getattr(coverage, "member_id", "") or "",
            "group": getattr(coverage, "group_number", "") or "",
            "plan_name": getattr(coverage, "plan_name", "") or "",
            "relationship": getattr(coverage, "subscriber_relation", "") or "Self",
        },
        "payer": {
            "name": payer_resolved.get("name", ""),
            "type": payer_resolved.get("type", ""),
            "claim_filing": payer_resolved.get("claim_filing", ""),
            "payer_id": payer_resolved.get("payer_id", ""),
            "address": " ".join(str(v) for v in (getattr(payer, "address", None) or {}).values()) if getattr(payer, "address", None) else "",
        },
        "rendering_provider": {"name": rp_name, "npi": rp_npi or "", "taxonomy": rp_tax or "", "credential": rp_cred or ""},
        "billing_provider": {
            "name": getattr(practice, "practice_name", "") or "",
            "npi": bp_npi or "",
            "tin": getattr(practice, "tin", "") or "",
            "address_1": getattr(practice, "address_line_1", "") or "",
            "address_2": getattr(practice, "address_line_2", "") or "",
            "city": getattr(practice, "city", "") or "",
            "state": getattr(practice, "state", "") or "",
            "zip": getattr(practice, "zip_code", "") or "",
            "phone": getattr(practice, "phone", "") or "",
        },
        "facility": {
            "name": getattr(practice, "practice_name", "") or "",
            "address_1": getattr(practice, "address_line_1", "") or "",
            "address_2": getattr(practice, "address_line_2", "") or "",
            "npi": bp_npi or "", "pos": pos,
        },
        "referring_provider": {"name": "", "npi": ""},
        "claim": {
            "account_no": getattr(claim, "claim_number", "") or "",
            "total_charge": _money(getattr(claim, "total_charge", 0)),
            "amount_paid": _money(getattr(claim, "total_paid", 0)),
            "dos_from": _d(getattr(encounter, "encounter_date", None)) or (_d(lines[0].service_date_from) if lines else ""),
            "dos_to": _d(lines[-1].service_date_from) if lines else "",
            "prior_auth": getattr(encounter, "prior_auth_number", "") or "",
            "type_of_bill": "0111", "admission_type": "", "discharge_status": "",
            "admit_date": "", "admitting_dx": dxs[0].icd10_code if dxs else "",
        },
        "diagnoses": [{"code": d.icd10_code, "description": ""} for d in dxs],
        "lines": [],
    }

    for ln in lines:
        mods = [getattr(ln, f"modifier_{i}", None) for i in range(1, 5)]
        ptrs_raw = [getattr(ln, f"icd_pointer_{i}", None) for i in range(1, 5)]
        ptrs = [_PTR_TO_LETTER.get(str(p), str(p)) for p in ptrs_raw if p]
        ctx["lines"].append({
            "dos_from": _d(getattr(ln, "service_date_from", None)),
            "dos_to": _d(getattr(ln, "service_date_to", None)) or _d(getattr(ln, "service_date_from", None)),
            "pos": getattr(ln, "place_of_service", "") or pos,
            "cpt": getattr(ln, "cpt_code", "") or "",
            "modifiers": [m for m in mods if m],
            "dx_pointers": ptrs,
            "charge": _money(getattr(ln, "charge_amount", 0)),
            "units": str(int(getattr(ln, "units", 1) or 1)),
            "revenue_code": getattr(ln, "revenue_code", "") or "",
            "rendering_npi": rp_npi or "",
        })

    form = build_form(form_type, ctx)
    edits = validate_form(form_type, form)
    return {"claim_id": str(claim.id), "form_type": form_type,
            "form": form, "edits": edits, "enrichment": enrichment}
