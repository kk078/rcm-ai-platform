"""Minimal X12 270 (Eligibility/Benefit Inquiry, 005010X279A1) generator.

Builds a single-subscriber real-time 270 suitable for a CAQH CORE clearinghouse or
CMS HETS (Medicare). Not a full implementation of every situational segment — it
carries the data required for a standard real-time eligibility inquiry.
"""
from __future__ import annotations

from datetime import datetime, date

ELEM = "*"
SUB = ":"
SEG = "~"


def _isa_control(now: datetime) -> str:
    return now.strftime("%y%m%d")  # ISA09 date (YYMMDD)


def build_270(
    *,
    sender_id: str,
    receiver_id: str,
    payer_name: str,
    payer_id: str,
    provider_last_or_org: str,
    provider_npi: str,
    subscriber_first: str,
    subscriber_last: str,
    member_id: str,
    subscriber_dob: date | None = None,
    service_type_code: str = "30",   # 30 = Health Benefit Plan Coverage (general)
    service_date: date | None = None,
    control_number: str = "000000001",
) -> str:
    """Return a 270 transaction string (ISA…IEA)."""
    now = datetime.utcnow()
    d8 = now.strftime("%Y%m%d")
    t4 = now.strftime("%H%M")
    dob = subscriber_dob.strftime("%Y%m%d") if subscriber_dob else ""
    svc = (service_date or date.today()).strftime("%Y%m%d")
    ctrl = control_number.zfill(9)

    segs: list[str] = []
    a = segs.append
    # Interchange / functional group envelopes
    a(ELEM.join([
        "ISA", "00", " " * 10, "00", " " * 10, "ZZ", sender_id.ljust(15)[:15],
        "ZZ", receiver_id.ljust(15)[:15], _isa_control(now), t4, "^", "00501",
        ctrl, "0", "P", SUB,
    ]))
    a(ELEM.join(["GS", "HS", sender_id, receiver_id, d8, t4, ctrl.lstrip("0") or "1", "X", "005010X279A1"]))
    a(ELEM.join(["ST", "270", "0001", "005010X279A1"]))
    a(ELEM.join(["BHT", "0022", "13", ctrl, d8, t4]))
    # 2100A Information Source (payer)
    a(ELEM.join(["HL", "1", "", "20", "1"]))
    a(ELEM.join(["NM1", "PR", "2", payer_name, "", "", "", "", "PI", payer_id]))
    # 2100B Information Receiver (provider)
    a(ELEM.join(["HL", "2", "1", "21", "1"]))
    a(ELEM.join(["NM1", "1P", "2", provider_last_or_org, "", "", "", "", "XX", provider_npi]))
    # 2100C Subscriber
    a(ELEM.join(["HL", "3", "2", "22", "0"]))
    a(ELEM.join(["TRN", "1", ctrl, "9" + (provider_npi or "0000000000")]))
    a(ELEM.join(["NM1", "IL", "1", subscriber_last, subscriber_first, "", "", "", "MI", member_id]))
    if dob:
        a(ELEM.join(["DMG", "D8", dob]))
    a(ELEM.join(["DTP", "291", "D8", svc]))   # 291 = Plan
    a(ELEM.join(["EQ", service_type_code]))
    # Trailers (segment count for SE = segments from ST..SE inclusive)
    st_index = next(i for i, s in enumerate(segs) if s.startswith("ST" + ELEM))
    se_count = len(segs) - st_index + 1
    a(ELEM.join(["SE", str(se_count), "0001"]))
    a(ELEM.join(["GE", "1", ctrl.lstrip("0") or "1"]))
    a(ELEM.join(["IEA", "1", ctrl]))
    return SEG.join(segs) + SEG
