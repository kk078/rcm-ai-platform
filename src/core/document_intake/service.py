"""Patient-document intake pipeline.

Flow:  upload bytes -> OCR/text extract -> LLM classify + structured extract ->
resolve Patient + Payer -> for eligibility/benefits create Coverage + EligibilityCheck
-> write a PatientDocument ledger row (provenance + dedup + structured JSON).

PHI: everything here is practice-scoped patient data and lives in the operational DB
(never the global reference knowledge base). Dedup is by sha256 of the extracted text.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import date, datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models import (
    PatientDocument, Patient, Payer, Coverage, EligibilityCheck, Practice,
)
from src.core.eligibility.plan_types import normalize_plan_type
from src.core.knowledge.service import extract_text_from_file

logger = structlog.get_logger()

DOC_TYPES = ("eligibility_benefits", "progress_note", "fee_schedule", "ehr_export", "eob_era", "other")
_DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m/%d/%y", "%m.%d.%Y", "%m.%d.%y")


def _hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", "ignore")).hexdigest()


def _parse_date(v) -> date | None:
    if not v:
        return None
    s = str(v).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", s)
    if m:
        mo, da, yr = m.groups()
        yr = ("20" + yr) if len(yr) == 2 else yr
        try:
            return date(int(yr), int(mo), int(da))
        except ValueError:
            return None
    return None


def _money(v) -> float | None:
    if v is None:
        return None
    s = re.sub(r"[^0-9.]", "", str(v))
    if not s:
        return None
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def _pct(v) -> int | None:
    f = _money(v)
    if f is None:
        return None
    p = int(round(f * 100)) if f <= 1 else int(round(f))
    return p if 0 <= p <= 100 else None  # reject mis-mapped dollar amounts (coinsurance is a %)


async def classify_and_extract(text: str) -> dict:
    """LLM: classify the document and pull structured fields. Best-effort -> {} on failure."""
    snippet = (text or "")[:9000]
    if not snippet.strip():
        return {}
    system = (
        "You are an RCM document parser. Classify a U.S. healthcare document and extract fields. "
        "Return ONLY JSON of this exact shape (omit unknown values, do not invent):\n"
        '{"doc_type":"eligibility_benefits|progress_note|fee_schedule|ehr_export|eob_era|other",'
        '"patient":{"first_name":"","last_name":"","date_of_birth":"","gender":"","member_id":""},'
        '"payer":{"name":"","payer_id":""},'
        '"benefits":{"coverage_status":"active|inactive","plan_type":"","plan_name":"","network_status":"in-network|out-of-network",'
        '"copay":"","deductible":"","deductible_met":"","out_of_pocket_max":"","coinsurance_pct":"","effective_date":"","termination_date":""},'
        '"summary":"one sentence"}'
    )
    try:
        from src.core.nlp.ai_service import get_ai_service  # noqa: PLC0415
        backend = get_ai_service()._get_backend()
        out, _ = await backend.call(system=system, user_content="Document text:\n\n" + snippet,
                                    use_json=False, max_tokens=1200)
        m = re.search(r"\{.*\}", out or "", re.DOTALL)
        if not m:
            return {}
        return json.loads(m.group(0))
    except Exception as e:  # noqa: BLE001
        logger.warning("doc_intake_extract_failed", error=str(e))
        return {}


async def _resolve_practice(db: AsyncSession, practice_id):
    """Patient records require a practice. If the uploader has none (e.g. a company-admin),
    fall back to the primary (first) practice so patient docs still land somewhere sensible."""
    if practice_id is not None:
        return practice_id
    p = (await db.execute(select(Practice).order_by(Practice.created_at).limit(1))).scalar_one_or_none()
    return p.id if p else None


async def _resolve_patient(db: AsyncSession, practice_id, p: dict) -> Patient | None:
    """Match an existing patient by DOB + last name (names are encrypted, so compare in Python);
    create one if not found and we have enough identity. Returns None if identity is too thin."""
    if not p:
        return None
    first = (p.get("first_name") or "").strip()
    last = (p.get("last_name") or "").strip()
    dob = _parse_date(p.get("date_of_birth"))
    if not (last and dob):
        return None  # not enough to safely create/link a patient

    if practice_id is not None:
        rows = (await db.execute(
            select(Patient).where(Patient.practice_id == practice_id, Patient.date_of_birth == dob)
        )).scalars().all()
        for cand in rows:
            if (cand.last_name or "").lower() == last.lower() and \
               (not first or (cand.first_name or "").lower().startswith(first.lower()[:3])):
                return cand

    patient = Patient(
        practice_id=practice_id,
        mrn=f"AUTO-{uuid.uuid4().hex[:10].upper()}",
        first_name=first or "Unknown",
        last_name=last,
        date_of_birth=dob,
        gender=(p.get("gender") or None),
        is_active=True,
    )
    db.add(patient)
    await db.flush()
    return patient


async def _resolve_payer(db: AsyncSession, payer: dict) -> Payer | None:
    if not payer:
        return None
    name = (payer.get("name") or "").strip()
    pid = (payer.get("payer_id") or "").strip()
    if not (name or pid):
        return None
    if pid:
        existing = (await db.execute(select(Payer).where(Payer.payer_id_number == pid))).scalar_one_or_none()
        if existing:
            return existing
    if name:
        existing = (await db.execute(select(Payer).where(Payer.payer_name.ilike(name)))).scalar_one_or_none()
        if existing:
            return existing
    payer_obj = Payer(
        payer_name=name or f"Payer {pid}",
        payer_id_number=pid or f"AUTO{uuid.uuid4().hex[:8].upper()}",
    )
    db.add(payer_obj)
    await db.flush()
    return payer_obj


async def ingest_patient_document(
    db: AsyncSession,
    *,
    practice_id: uuid.UUID | None,
    filename: str,
    data: bytes | None = None,
    added_by_id: uuid.UUID | None = None,
    text: str | None = None,
    parsed: dict | None = None,
) -> dict:
    """Full pipeline. Returns a summary dict (doc_type, links, dedup flag).
    `text` / `parsed` may be supplied to avoid a second OCR / classification pass."""
    if text is None:
        text = extract_text_from_file(filename, data or b"")  # OCRs scanned / glyph-garbage PDFs
    if not text:
        raise ValueError("No text could be extracted from the document.")
    chash = _hash(text)

    dup = (await db.execute(
        select(PatientDocument).where(PatientDocument.content_hash == chash).limit(1)
    )).scalar_one_or_none()
    if dup:
        return {"duplicate": True, "document_id": str(dup.id), "doc_type": dup.doc_type,
                "patient_id": str(dup.patient_id) if dup.patient_id else None,
                "message": f"Duplicate of an already-ingested document ({dup.doc_type})."}

    practice_id = await _resolve_practice(db, practice_id)  # patient records require a practice

    if parsed is None:
        parsed = await classify_and_extract(text)
    doc_type = parsed.get("doc_type") if parsed.get("doc_type") in DOC_TYPES else "other"

    patient = await _resolve_patient(db, practice_id, parsed.get("patient") or {})
    payer = await _resolve_payer(db, parsed.get("payer") or {})
    coverage = None
    elig = None
    status = "processed"
    note = parsed.get("summary")

    if doc_type == "eligibility_benefits" and patient is not None:
        b = parsed.get("benefits") or {}
        pinfo = parsed.get("patient") or {}
        plan_type = normalize_plan_type(b.get("plan_type"))
        eff = _parse_date(b.get("effective_date")) or date.today()
        member_id = (pinfo.get("member_id") or "").strip() or None

        if payer is not None and member_id:
            coverage = (await db.execute(select(Coverage).where(
                Coverage.patient_id == patient.id, Coverage.payer_id == payer.id,
                Coverage.member_id == member_id,
            ).limit(1))).scalar_one_or_none()
        if coverage is None and payer is not None:
            coverage = Coverage(
                practice_id=practice_id, patient_id=patient.id, payer_id=payer.id,
                member_id=member_id or "UNKNOWN", group_number=None,
                plan_name=b.get("plan_name"), plan_type=plan_type,
                coverage_type="primary", subscriber_relation="self",
                effective_date=eff, termination_date=_parse_date(b.get("termination_date")),
                copay_amount=_money(b.get("copay")),
                deductible_amount=_money(b.get("deductible")),
                deductible_met=_money(b.get("deductible_met")),
                coinsurance_pct=_pct(b.get("coinsurance_pct")),
                verified_at=datetime.now(timezone.utc).replace(tzinfo=None), is_active=True,
            )
            db.add(coverage)
            await db.flush()

        active = (b.get("coverage_status") or "").lower() != "inactive"
        elig = EligibilityCheck(
            practice_id=practice_id, patient_id=patient.id,
            coverage_id=coverage.id if coverage else None,
            payer_id=payer.id if payer else None,
            status="active" if active else "inactive", is_active=active,
            check_date=datetime.now(timezone.utc).replace(tzinfo=None), service_date=date.today(),
            plan_name=b.get("plan_name"), plan_type=plan_type,
            network_status=b.get("network_status") or "unknown",
            deductible_total=_money(b.get("deductible")),
            deductible_met=_money(b.get("deductible_met")),
            oop_total=_money(b.get("out_of_pocket_max")),
            copay=_money(b.get("copay")), coinsurance_pct=_pct(b.get("coinsurance_pct")),
            checked_by_id=added_by_id,
            raw_response={"source": "document_upload", "filename": filename},
        )
        db.add(elig)
        await db.flush()
    elif patient is None and doc_type == "eligibility_benefits":
        status = "needs_review"
        note = "Eligibility doc parsed but patient identity (name + DOB) could not be resolved."

    ledger = PatientDocument(
        practice_id=practice_id, doc_type=doc_type, source_filename=filename,
        content_hash=chash, raw_text=text[:200000], extracted=parsed,
        patient_id=patient.id if patient else None,
        payer_id=payer.id if payer else None,
        coverage_id=coverage.id if coverage else None,
        eligibility_check_id=elig.id if elig else None,
        status=status, note=note, added_by_id=added_by_id,
    )
    db.add(ledger)
    await db.flush()
    logger.info("patient_document_ingested", doc_type=doc_type, status=status,
                patient=bool(patient), coverage=bool(coverage), elig=bool(elig))
    return {
        "duplicate": False, "document_id": str(ledger.id), "doc_type": doc_type, "status": status,
        "patient_id": str(patient.id) if patient else None,
        "payer_id": str(payer.id) if payer else None,
        "coverage_id": str(coverage.id) if coverage else None,
        "eligibility_check_id": str(elig.id) if elig else None,
        "summary": note,
    }
