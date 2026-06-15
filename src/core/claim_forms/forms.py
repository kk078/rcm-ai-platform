"""Map an assembled claim context → the full field set of the CMS-1500 and UB-04.

Output shape (consumed by the staff-portal review screen):
{
  "form_type": "cms1500" | "ub04",
  "sections": [ {"title": str, "fields": [ {"key","label","value"} ] } ],
  "diagnoses": [ {"pointer","code","description"} ],        # box 21 / FL67
  "service_lines": [ {<line fields>} ],                      # box 24 / FL42-47
}
validate_* returns [ {"code","severity","field","message"} ].
"""
from __future__ import annotations

from typing import Any

_LETTERS = list("ABCDEFGHIJKL")


def _g(d: dict, *keys, default=""):
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur not in (None, "") else default


# ── CMS-1500 (professional, 02/12) ───────────────────────────────────────────
def build_cms1500(ctx: dict) -> dict:
    pat = ctx.get("patient", {})
    ins = ctx.get("insured", {})
    payer = ctx.get("payer", {})
    rp = ctx.get("rendering_provider", {})
    bp = ctx.get("billing_provider", {})
    fac = ctx.get("facility", {})
    ref = ctx.get("referring_provider", {})
    clm = ctx.get("claim", {})

    pat_addr = f"{_g(pat,'address_1')} {_g(pat,'address_2')}".strip()
    bp_addr = f"{_g(bp,'address_1')} {_g(bp,'address_2')}".strip()
    fac_addr = f"{_g(fac,'address_1')} {_g(fac,'address_2')}".strip()

    sections = [
        {"title": "Carrier / Insurance", "fields": [
            {"key": "box1_insurance_type", "label": "1. Insurance Type", "value": payer.get("type", "")},
            {"key": "box1a_insured_id", "label": "1a. Insured's ID #", "value": ins.get("id", "")},
            {"key": "carrier_name", "label": "Payer Name", "value": payer.get("name", "")},
            {"key": "carrier_addr", "label": "Payer Address", "value": payer.get("address", "")},
        ]},
        {"title": "Patient (Boxes 2-8)", "fields": [
            {"key": "box2_patient_name", "label": "2. Patient Name (Last, First MI)", "value": pat.get("name", "")},
            {"key": "box3_patient_dob", "label": "3. Patient DOB", "value": pat.get("dob", "")},
            {"key": "box3_patient_sex", "label": "3. Sex", "value": pat.get("sex", "")},
            {"key": "box5_patient_addr", "label": "5. Patient Address", "value": pat_addr},
            {"key": "box5_patient_city", "label": "5. City", "value": pat.get("city", "")},
            {"key": "box5_patient_state", "label": "5. State", "value": pat.get("state", "")},
            {"key": "box5_patient_zip", "label": "5. ZIP", "value": pat.get("zip", "")},
            {"key": "box5_patient_phone", "label": "5. Phone", "value": pat.get("phone", "")},
            {"key": "box6_relationship", "label": "6. Patient Rel. to Insured", "value": ins.get("relationship", "Self")},
        ]},
        {"title": "Insured (Boxes 4, 7, 11)", "fields": [
            {"key": "box4_insured_name", "label": "4. Insured's Name", "value": ins.get("name", pat.get("name", ""))},
            {"key": "box7_insured_addr", "label": "7. Insured's Address", "value": ins.get("address", pat_addr)},
            {"key": "box11_group", "label": "11. Insured's Group/Policy #", "value": ins.get("group", "")},
            {"key": "box11c_plan_name", "label": "11c. Insurance Plan Name", "value": ins.get("plan_name", payer.get("name", ""))},
        ]},
        {"title": "Condition / Dates (Boxes 10, 14-23)", "fields": [
            {"key": "box10a_employment", "label": "10a. Related to Employment", "value": "NO"},
            {"key": "box10b_auto", "label": "10b. Auto Accident", "value": "NO"},
            {"key": "box10c_other", "label": "10c. Other Accident", "value": "NO"},
            {"key": "box14_onset_date", "label": "14. Date of Current Illness", "value": clm.get("onset_date", "")},
            {"key": "box17_referring", "label": "17. Referring Provider", "value": ref.get("name", "")},
            {"key": "box17b_referring_npi", "label": "17b. Referring NPI", "value": ref.get("npi", "")},
            {"key": "box18_hosp_from", "label": "18. Hospitalization From", "value": clm.get("hosp_from", "")},
            {"key": "box18_hosp_to", "label": "18. Hospitalization To", "value": clm.get("hosp_to", "")},
            {"key": "box21_icd_indicator", "label": "21. ICD Indicator", "value": "0 (ICD-10)"},
            {"key": "box23_prior_auth", "label": "23. Prior Authorization #", "value": clm.get("prior_auth", "")},
        ]},
        {"title": "Billing / Totals (Boxes 25-33)", "fields": [
            {"key": "box25_federal_tin", "label": "25. Federal Tax ID (EIN)", "value": bp.get("tin", "")},
            {"key": "box26_account_no", "label": "26. Patient Account #", "value": clm.get("account_no", "")},
            {"key": "box27_accept_assign", "label": "27. Accept Assignment", "value": "YES"},
            {"key": "box28_total_charge", "label": "28. Total Charge", "value": clm.get("total_charge", "0.00")},
            {"key": "box29_amount_paid", "label": "29. Amount Paid", "value": clm.get("amount_paid", "0.00")},
            {"key": "box31_signature", "label": "31. Physician Signature", "value": rp.get("name", "")},
            {"key": "box32_facility_name", "label": "32. Service Facility", "value": fac.get("name", "")},
            {"key": "box32_facility_addr", "label": "32. Facility Address", "value": fac_addr},
            {"key": "box32a_facility_npi", "label": "32a. Facility NPI", "value": fac.get("npi", "")},
            {"key": "box33_billing_name", "label": "33. Billing Provider", "value": bp.get("name", "")},
            {"key": "box33_billing_addr", "label": "33. Billing Address", "value": bp_addr},
            {"key": "box33_billing_phone", "label": "33. Billing Phone", "value": bp.get("phone", "")},
            {"key": "box33a_billing_npi", "label": "33a. Billing NPI (Group)", "value": bp.get("npi", "")},
            {"key": "box33b_taxonomy", "label": "33b. Taxonomy", "value": rp.get("taxonomy", "")},
        ]},
    ]

    diagnoses = []
    for i, d in enumerate(ctx.get("diagnoses", [])[:12]):
        diagnoses.append({"pointer": _LETTERS[i], "code": d.get("code", ""), "description": d.get("description", "")})

    service_lines = []
    for ln in ctx.get("lines", [])[:6]:
        service_lines.append({
            "dos_from": ln.get("dos_from", ""),
            "dos_to": ln.get("dos_to", ln.get("dos_from", "")),
            "pos": ln.get("pos", ""),
            "emg": ln.get("emg", ""),
            "cpt": ln.get("cpt", ""),
            "modifiers": ", ".join(ln.get("modifiers", []) or []),
            "dx_pointers": "".join(ln.get("dx_pointers", []) or []),
            "charges": ln.get("charge", "0.00"),
            "units": ln.get("units", "1"),
            "rendering_npi": ln.get("rendering_npi", rp.get("npi", "")),
        })

    return {"form_type": "cms1500", "sections": sections,
            "diagnoses": diagnoses, "service_lines": service_lines}


def validate_cms1500(form: dict) -> list[dict]:
    edits: list[dict] = []
    flat = {f["key"]: f["value"] for s in form.get("sections", []) for f in s["fields"]}

    def need(key, label, code):
        if not str(flat.get(key, "")).strip():
            edits.append({"code": code, "severity": "error", "field": key,
                          "message": f"{label} is required for submission."})

    need("box1a_insured_id", "Insured's ID (1a)", "CMS1A")
    need("box2_patient_name", "Patient name (2)", "CMS02")
    need("box3_patient_dob", "Patient DOB (3)", "CMS03")
    need("box25_federal_tin", "Federal Tax ID (25)", "CMS25")
    need("box33a_billing_npi", "Billing NPI (33a)", "CMS33A")
    if not form.get("diagnoses"):
        edits.append({"code": "CMS21", "severity": "error", "field": "diagnoses",
                      "message": "At least one ICD-10 diagnosis (box 21) is required."})
    if not form.get("service_lines"):
        edits.append({"code": "CMS24", "severity": "error", "field": "service_lines",
                      "message": "At least one service line (box 24) is required."})
    for i, ln in enumerate(form.get("service_lines", []), 1):
        if not str(ln.get("cpt", "")).strip():
            edits.append({"code": "CMS24D", "severity": "error", "field": f"line{i}.cpt",
                          "message": f"Line {i}: CPT/HCPCS (24D) is required."})
        if not str(ln.get("rendering_npi", "")).strip():
            edits.append({"code": "CMS24J", "severity": "warning", "field": f"line{i}.rendering_npi",
                          "message": f"Line {i}: Rendering provider NPI (24J) is missing."})
        if not str(ln.get("dx_pointers", "")).strip():
            edits.append({"code": "CMS24E", "severity": "warning", "field": f"line{i}.dx_pointers",
                          "message": f"Line {i}: diagnosis pointer (24E) is missing."})
    return edits


# ── UB-04 (institutional, CMS-1450) ──────────────────────────────────────────
def build_ub04(ctx: dict) -> dict:
    pat = ctx.get("patient", {})
    ins = ctx.get("insured", {})
    payer = ctx.get("payer", {})
    bp = ctx.get("billing_provider", {})
    fac = ctx.get("facility", {})
    att = ctx.get("rendering_provider", {})  # attending = rendering for our context
    clm = ctx.get("claim", {})

    bp_addr = f"{_g(bp,'address_1')} {_g(bp,'address_2')}, {_g(bp,'city')} {_g(bp,'state')} {_g(bp,'zip')}".strip()
    pat_addr = f"{_g(pat,'address_1')} {_g(pat,'address_2')}".strip()

    sections = [
        {"title": "Provider / Patient (FL1-FL17)", "fields": [
            {"key": "fl1_billing_provider", "label": "FL1. Billing Provider Name/Addr", "value": f"{bp.get('name','')} — {bp_addr}"},
            {"key": "fl3a_patient_control", "label": "FL3a. Patient Control #", "value": clm.get("account_no", "")},
            {"key": "fl3b_med_record", "label": "FL3b. Medical Record #", "value": pat.get("mrn", "")},
            {"key": "fl4_type_of_bill", "label": "FL4. Type of Bill", "value": clm.get("type_of_bill", "0111")},
            {"key": "fl5_federal_tax", "label": "FL5. Federal Tax #", "value": bp.get("tin", "")},
            {"key": "fl6_statement_from", "label": "FL6. Statement From", "value": clm.get("dos_from", "")},
            {"key": "fl6_statement_to", "label": "FL6. Statement Through", "value": clm.get("dos_to", "")},
            {"key": "fl8b_patient_name", "label": "FL8b. Patient Name", "value": pat.get("name", "")},
            {"key": "fl9_patient_addr", "label": "FL9. Patient Address", "value": f"{pat_addr}, {_g(pat,'city')} {_g(pat,'state')} {_g(pat,'zip')}".strip()},
            {"key": "fl10_birthdate", "label": "FL10. Birthdate", "value": pat.get("dob", "")},
            {"key": "fl11_sex", "label": "FL11. Sex", "value": pat.get("sex", "")},
            {"key": "fl12_admission_date", "label": "FL12. Admission Date", "value": clm.get("admit_date", "")},
            {"key": "fl14_admission_type", "label": "FL14. Type of Admission", "value": clm.get("admission_type", "")},
            {"key": "fl17_discharge_status", "label": "FL17. Patient Discharge Status", "value": clm.get("discharge_status", "")},
        ]},
        {"title": "Payer / Insured (FL50-FL65)", "fields": [
            {"key": "fl50_payer", "label": "FL50A. Payer Name", "value": payer.get("name", "")},
            {"key": "fl51_health_plan_id", "label": "FL51A. Health Plan ID", "value": payer.get("payer_id", "")},
            {"key": "fl52_rel_info", "label": "FL52A. Release of Info", "value": "Y"},
            {"key": "fl53_assign_benefits", "label": "FL53A. Assignment of Benefits", "value": "Y"},
            {"key": "fl56_billing_npi", "label": "FL56. Billing Provider NPI", "value": bp.get("npi", "")},
            {"key": "fl58_insured_name", "label": "FL58A. Insured's Name", "value": ins.get("name", pat.get("name", ""))},
            {"key": "fl59_patient_rel", "label": "FL59A. Patient Rel to Insured", "value": ins.get("relationship", "18 (Self)")},
            {"key": "fl60_insured_id", "label": "FL60A. Insured's Unique ID", "value": ins.get("id", "")},
            {"key": "fl61_group_name", "label": "FL61A. Group Name", "value": ins.get("plan_name", payer.get("name", ""))},
            {"key": "fl62_group_number", "label": "FL62A. Insurance Group #", "value": ins.get("group", "")},
            {"key": "fl63_treatment_auth", "label": "FL63A. Treatment Auth Code", "value": clm.get("prior_auth", "")},
        ]},
        {"title": "Diagnosis / Provider (FL66-FL81)", "fields": [
            {"key": "fl66_dx_version", "label": "FL66. DX Version Qualifier", "value": "0 (ICD-10)"},
            {"key": "fl69_admitting_dx", "label": "FL69. Admitting Diagnosis", "value": clm.get("admitting_dx", "")},
            {"key": "fl76_attending_npi", "label": "FL76. Attending NPI", "value": att.get("npi", "")},
            {"key": "fl76_attending_name", "label": "FL76. Attending Name", "value": att.get("name", "")},
            {"key": "fl55_est_amount_due", "label": "FL55. Est. Amount Due", "value": clm.get("total_charge", "0.00")},
        ]},
    ]

    # FL67 principal + other diagnoses (A-Q)
    diagnoses = []
    for i, d in enumerate(ctx.get("diagnoses", [])[:18]):
        diagnoses.append({"pointer": "Principal" if i == 0 else _LETTERS[(i - 1) % 12],
                          "code": d.get("code", ""), "description": d.get("description", "")})

    # FL42-47 revenue lines
    service_lines = []
    for ln in ctx.get("lines", []):
        service_lines.append({
            "fl42_revenue_code": ln.get("revenue_code", "0510"),
            "fl43_description": ln.get("description", ""),
            "fl44_hcpcs": ln.get("cpt", ""),
            "fl45_service_date": ln.get("dos_from", ""),
            "fl46_units": ln.get("units", "1"),
            "fl47_total_charges": ln.get("charge", "0.00"),
        })
    return {"form_type": "ub04", "sections": sections,
            "diagnoses": diagnoses, "service_lines": service_lines}


def validate_ub04(form: dict) -> list[dict]:
    edits: list[dict] = []
    flat = {f["key"]: f["value"] for s in form.get("sections", []) for f in s["fields"]}

    def need(key, label, code):
        if not str(flat.get(key, "")).strip():
            edits.append({"code": code, "severity": "error", "field": key,
                          "message": f"{label} is required for submission."})

    need("fl4_type_of_bill", "Type of Bill (FL4)", "UB04")
    need("fl56_billing_npi", "Billing NPI (FL56)", "UB56")
    need("fl60_insured_id", "Insured's ID (FL60)", "UB60")
    need("fl76_attending_npi", "Attending NPI (FL76)", "UB76")
    if not form.get("diagnoses"):
        edits.append({"code": "UB67", "severity": "error", "field": "diagnoses",
                      "message": "Principal diagnosis (FL67) is required."})
    if not form.get("service_lines"):
        edits.append({"code": "UB42", "severity": "error", "field": "service_lines",
                      "message": "At least one revenue line (FL42-47) is required."})
    return edits


def build_form(form_type: str, ctx: dict) -> dict:
    return build_ub04(ctx) if form_type == "ub04" else build_cms1500(ctx)


def validate_form(form_type: str, form: dict) -> list[dict]:
    return validate_ub04(form) if form_type == "ub04" else validate_cms1500(form)
