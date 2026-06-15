"""Import an external PMS/EHR payer-claim-aging file into the AR follow-up work queue.

An aging export is *summary* AR (payer, patient, claim #, service date, balance, aging
bucket) — not full claim detail — so each open line becomes a WorkQueueItem
(queue_type='follow_up', item_type='external_ar') carrying the row as JSON in `notes`
for the AR/denial agent (and staff) to work, prioritized by aging bucket.

Robust to the messy real-world exports we see: tab- or comma-delimited despite a .csv
extension, header aliases across PMS vendors, $/comma-formatted money, leading junk
columns. Dedup is by (practice, claim_no). Credit balances (<0) are flagged but still
imported (they need working too); zero balances are skipped.
"""
from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import datetime, timezone, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models import WorkQueueItem

logger = structlog.get_logger()

# PMS header (lowercased/stripped) -> canonical key. Extend as new vendors appear.
_ALIASES = {
    "payer name": "payer", "payer": "payer", "insurance": "payer",
    "patient name": "patient", "patient": "patient",
    "patient acct no": "acct", "account no": "acct", "account number": "acct", "patient account": "acct",
    "patient dob": "dob", "dob": "dob", "date of birth": "dob",
    "payer subscriber no": "member_id", "subscriber no": "member_id", "member id": "member_id",
    "payer group no": "group_no", "group no": "group_no",
    "aging days": "aging_days", "age": "aging_days", "days": "aging_days",
    "service date": "service_date", "dos": "service_date",
    "claim date": "claim_date",
    "claim no": "claim_no", "claim number": "claim_no", "claim #": "claim_no",
    "charges": "charges", "charge": "charges", "total charges": "charges",
    "balance": "balance", "open balance": "balance", "amount due": "balance",
    "last submission date": "last_submission",
    "last claim status change date": "last_status_change",
    "current": "b_current", "0-30": "b_current",
    "31-60": "b_31_60", "61-90": "b_61_90", "91-120": "b_91_120",
    "> 120": "b_120p", ">120": "b_120p", "over 120": "b_120p", "120+": "b_120p",
}


def _num(v) -> float:
    if v is None:
        return 0.0
    s = str(v).replace(",", "").replace("$", "").replace("(", "-").replace(")", "").strip()
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _bucket_and_priority(aging_days, row: dict):
    try:
        d = int(float(aging_days))
    except (TypeError, ValueError):
        d = 0
    # Prefer explicit bucket columns when present (some exports leave aging_days blank).
    if _num(row.get("b_120p")) or d > 120:
        return ">120", 95
    if _num(row.get("b_91_120")) or d > 90:
        return "91-120", 85
    if _num(row.get("b_61_90")) or d > 60:
        return "61-90", 75
    if _num(row.get("b_31_60")) or d > 30:
        return "31-60", 65
    return "0-30", 45


def _decode(data: bytes) -> str:
    # PMS exports are frequently UTF-16 (BOM or interleaved NULs); fall back to UTF-8.
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", "ignore")
    if data[:4096].count(b"\x00") > 64:
        return data.decode("utf-16", "ignore")
    return data.decode("utf-8-sig", "ignore")


def _reader(data: bytes):
    text = _decode(data)
    first = text.split("\n", 1)[0]
    # Pick the delimiter that best splits the *header* line (handles .csv files that
    # are actually tab/pipe/semicolon delimited).
    delim = max(["\t", ",", "|", ";"], key=lambda d: first.count(d))
    if first.count(delim) == 0:
        delim = ","
    return csv.DictReader(io.StringIO(text), delimiter=delim)


async def import_open_ar(db: AsyncSession, *, practice_id, data: bytes, added_by_id=None) -> dict:
    """Parse an aging export and create follow-up queue items. Returns a summary dict."""
    reader = _reader(data)
    fieldmap = {}
    for h in (reader.fieldnames or []):
        key = _ALIASES.get((h or "").strip().lower())
        if key and h not in fieldmap:
            fieldmap[h] = key
    if "balance" not in fieldmap.values() and "claim_no" not in fieldmap.values():
        raise ValueError("Unrecognized aging file — need at least a claim number and balance column.")

    # Dedup against AR already imported for this practice.
    existing: set[str] = set()
    for n in (await db.execute(
        select(WorkQueueItem.notes).where(
            WorkQueueItem.practice_id == practice_id,
            WorkQueueItem.item_type == "external_ar",
        )
    )).scalars().all():
        try:
            cn = json.loads(n).get("claim_no")
            if cn:
                existing.add(cn)
        except Exception:  # noqa: BLE001
            continue

    imported = dup = skipped_zero = credits = 0
    total_ar = 0.0
    buckets = {">120": 0, "91-120": 0, "61-90": 0, "31-60": 0, "0-30": 0}
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    for raw in reader:
        row = {}
        for h, key in fieldmap.items():
            row[key] = (raw.get(h) or "").strip()
        claim_no = row.get("claim_no") or ""
        balance = _num(row.get("balance"))
        if balance == 0:
            skipped_zero += 1
            continue
        if claim_no and claim_no in existing:
            dup += 1
            continue
        is_credit = balance < 0
        if is_credit:
            credits += 1
        bucket, prio = _bucket_and_priority(row.get("aging_days"), row)
        if not is_credit:
            total_ar += balance
            buckets[bucket] += 1
        payload = {
            "source": "pms_aging_import",
            "claim_no": claim_no, "payer": row.get("payer"),
            "patient": row.get("patient"), "acct": row.get("acct"), "dob": row.get("dob"),
            "member_id": row.get("member_id"), "group_no": row.get("group_no"),
            "service_date": row.get("service_date"), "claim_date": row.get("claim_date"),
            "aging_days": row.get("aging_days"), "charges": _num(row.get("charges")),
            "balance": round(balance, 2), "bucket": bucket, "is_credit": is_credit,
            "last_submission": row.get("last_submission"),
            "action": "resolve_credit_balance" if is_credit else "follow_up_open_ar",
        }
        db.add(WorkQueueItem(
            practice_id=practice_id, queue_type="follow_up", item_type="external_ar",
            item_id=uuid.uuid4(), priority=prio, status="pending",
            due_date=now + timedelta(days=3 if prio >= 85 else 7),
            notes=json.dumps(payload), assigned_to=None,
        ))
        if claim_no:
            existing.add(claim_no)
        imported += 1

    await db.flush()
    logger.info("ar_aging_imported", practice_id=str(practice_id), imported=imported,
                duplicates=dup, open_ar_total=round(total_ar, 2))
    return {
        "rows_imported": imported, "duplicates_skipped": dup,
        "zero_balance_skipped": skipped_zero, "credit_balances": credits,
        "open_ar_total": round(total_ar, 2), "aging_buckets": buckets,
        "headers_mapped": sorted(set(fieldmap.values())),
    }
