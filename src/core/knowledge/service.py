"""Knowledge-base service: ingest reference URLs / pasted text and retrieve them
via Postgres full-text search. No external embedding model required.

Used by the AI assistant (citable answers + URL ingestion from chat) and by the
AI dispatch agents (relevant reference context injected into the work payload).

Store NON-PHI reference material only (payer guidance, CMS/USA.gov pages, coding rules).
"""
from __future__ import annotations

import hashlib
import html
import re
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models import KnowledgeReference

logger = structlog.get_logger()

MAX_CONTENT_CHARS = 60_000
_URL_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_WS_RE = re.compile(r"[ \t\f\v]+")
_MULTINL_RE = re.compile(r"\n{3,}")

# ── PHI de-identification: the reference library stores NON-PHI knowledge ONLY.
# Genuine patient documents are routed to the operational tables; this is the
# deterministic backstop that scrubs HIPAA direct identifiers from anything that
# still reaches the KB (a payer/CMS doc that happens to embed a patient example).
_PHI_LABELED_RE = re.compile(
    r"(?im)^[ \t]*(patient(?:\s*name)?|name|member(?:\s*(?:id|name|no|#))?|subscriber(?:\s*(?:id|name|no|#))?|"
    r"policy(?:\s*(?:id|number|no|#))?|group(?:\s*(?:number|no|#))|mrn|medical\s*record(?:\s*(?:no|number|#))?|"
    r"guarantor|insured(?:\s*name)?|account(?:\s*(?:no|number|#))?)[ \t]*[:#][ \t]*.+$"
)
_DOB_RE = re.compile(
    r"(?i)\b(dob|d\.?o\.?b\.?|date\s*of\s*birth)\b[ \t]*[:\-]?[ \t]*\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}"
)
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_PHONE_RE = re.compile(r"\b\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_ADDR_RE = re.compile(
    r"(?i)\b\d{1,6}\s+(?:[A-Z][A-Za-z]+\.?\s+){1,3}"
    r"(?:st|street|ave|avenue|rd|road|blvd|dr|drive|lane|ln|way|ct|court|pl|place|ter|terrace|hwy|highway)\b\.?"
)


def _deidentify(text: str) -> str:
    """Redact HIPAA direct identifiers so no PHI is persisted in the reference KB."""
    if not text:
        return text
    out = _PHI_LABELED_RE.sub(lambda m: f"{m.group(1)}: [REDACTED]", text)
    out = _DOB_RE.sub(lambda m: f"{m.group(1)}: [REDACTED]", out)
    out = _SSN_RE.sub("[SSN]", out)
    out = _PHONE_RE.sub("[PHONE]", out)
    out = _EMAIL_RE.sub("[EMAIL]", out)
    out = _ADDR_RE.sub("[ADDRESS]", out)
    return out


def extract_urls(text: str | None) -> list[str]:
    """Return distinct http(s) URLs found in free text (trailing punctuation trimmed)."""
    if not text:
        return []
    out, seen = [], set()
    for m in _URL_RE.findall(text):
        u = m.rstrip(".,;:)]}'\"")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def html_to_text(raw: str) -> tuple[str, str | None]:
    """Strip HTML to readable text. Returns (text, title)."""
    if not raw:
        return "", None
    title_m = _TITLE_RE.search(raw)
    title = html.unescape(_TAG_RE.sub("", title_m.group(1))).strip() if title_m else None
    body = _SCRIPT_STYLE_RE.sub(" ", raw)
    body = _TAG_RE.sub(" ", body)
    body = html.unescape(body)
    body = _WS_RE.sub(" ", body)
    body = _MULTINL_RE.sub("\n\n", body)
    lines = [ln.strip() for ln in body.splitlines()]
    text = "\n".join(ln for ln in lines if ln).strip()
    return text, title


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", "ignore")).hexdigest()


async def ingest_url(
    db: AsyncSession,
    *,
    practice_id: uuid.UUID | None,
    url: str,
    added_by_id: uuid.UUID | None = None,
    tags: list | None = None,
    title: str | None = None,
) -> KnowledgeReference:
    """Fetch a URL server-side, extract readable text, and store it as a reference."""
    import httpx

    headers = {"User-Agent": "Aethera-RCM/1.0 (+eligibility knowledge base)"}
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True, headers=headers) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        raw = resp.text

    text, page_title = html_to_text(raw)
    if not text:
        raise ValueError("No readable text extracted from the page.")
    text = text[:MAX_CONTENT_CHARS]
    final_title = (title or page_title or url)[:300]

    return await _store(
        db, practice_id=practice_id, title=final_title, url=url, source_type="url",
        content=text, added_by_id=added_by_id, tags=tags,
    )


async def ingest_text(
    db: AsyncSession,
    *,
    practice_id: uuid.UUID | None,
    title: str,
    content: str,
    url: str | None = None,
    added_by_id: uuid.UUID | None = None,
    tags: list | None = None,
) -> KnowledgeReference:
    """Store pasted reference text directly."""
    content = (content or "").strip()
    if not content:
        raise ValueError("content is required.")
    return await _store(
        db, practice_id=practice_id, title=(title or "Untitled reference")[:300],
        url=url, source_type=("url" if url else "text"),
        content=content[:MAX_CONTENT_CHARS], added_by_id=added_by_id, tags=tags,
    )


async def _store(db, *, practice_id, title, url, source_type, content, added_by_id, tags):
    content = _deidentify(content)  # KB is NON-PHI: scrub identifiers before hashing/storing
    chash = _hash(content)
    # Dedupe within a practice scope by content hash; refresh fetched_at if unchanged.
    existing = (await db.execute(
        select(KnowledgeReference).where(
            KnowledgeReference.content_hash == chash,
            or_(KnowledgeReference.practice_id == practice_id,
                KnowledgeReference.practice_id.is_(None) if practice_id is None else False),
        ).limit(1)
    )).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if existing:
        existing.fetched_at = now
        existing.title = title
        existing.status = "active"
        await db.flush()
        return existing

    # Auto-structure: LLM summary + controlled topic tags (best-effort).
    summary, auto_tags = await summarize_and_tag(content)
    if not tags:
        tags = auto_tags

    ref = KnowledgeReference(
        practice_id=practice_id, title=title, url=url, source_type=source_type,
        content=content, content_hash=chash, char_count=len(content),
        tags=tags, summary=summary, status="active", fetched_at=now, added_by_id=added_by_id,
    )
    db.add(ref)
    await db.flush()
    logger.info("knowledge_reference_stored", title=title, chars=len(content), source=source_type)
    return ref


def _tsv(model):
    return func.to_tsvector("english", func.coalesce(model.title, "") + " " + func.coalesce(model.content, ""))


async def search_references(
    db: AsyncSession,
    *,
    practice_id: uuid.UUID | None,
    query: str,
    limit: int = 4,
) -> list[KnowledgeReference]:
    """Full-text search active references (practice-scoped + global), ranked. Falls back to ILIKE."""
    if not query or not query.strip():
        return []
    scope = or_(KnowledgeReference.practice_id == practice_id, KnowledgeReference.practice_id.is_(None))
    tsv = _tsv(KnowledgeReference)
    tsq = func.plainto_tsquery("english", query)
    stmt = (
        select(KnowledgeReference)
        .where(KnowledgeReference.status == "active", scope, tsv.op("@@")(tsq))
        .order_by(func.ts_rank(tsv, tsq).desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()
    if rows:
        return list(rows)
    # Fallback: simple ILIKE on the longest token (handles short/stopword queries).
    tokens = sorted((re.findall(r"[A-Za-z0-9]{4,}", query)), key=len, reverse=True)
    if not tokens:
        return []
    like = f"%{tokens[0]}%"
    stmt2 = (
        select(KnowledgeReference)
        .where(KnowledgeReference.status == "active", scope,
               or_(KnowledgeReference.content.ilike(like), KnowledgeReference.title.ilike(like)))
        .order_by(KnowledgeReference.fetched_at.desc().nullslast())
        .limit(limit)
    )
    return list((await db.execute(stmt2)).scalars().all())


def build_reference_context(refs: list[KnowledgeReference], max_chars_each: int = 1200) -> str:
    """Render references into a compact, citable context block for an LLM prompt."""
    if not refs:
        return ""
    parts = ["REFERENCE MATERIAL (cite by [n] title/URL; use only if relevant):"]
    for i, r in enumerate(refs, 1):
        snippet = (r.content or "")[:max_chars_each].strip()
        src = f" ({r.url})" if r.url else ""
        parts.append(f"[{i}] {r.title}{src}\n{snippet}")
    return "\n\n".join(parts)


async def list_references(db, *, practice_id, include_global=True, limit=100):
    scope = (or_(KnowledgeReference.practice_id == practice_id, KnowledgeReference.practice_id.is_(None))
             if include_global else KnowledgeReference.practice_id == practice_id)
    stmt = (select(KnowledgeReference).where(scope)
            .order_by(KnowledgeReference.created_at.desc()).limit(limit))
    return list((await db.execute(stmt)).scalars().all())


async def get_reference(db, ref_id: uuid.UUID):
    return (await db.execute(select(KnowledgeReference).where(KnowledgeReference.id == ref_id))).scalar_one_or_none()


async def delete_reference(db, ref_id: uuid.UUID) -> bool:
    ref = await get_reference(db, ref_id)
    if not ref:
        return False
    ref.status = "archived"
    await db.flush()
    return True


# ── Auto-structuring (LLM summary + controlled topic tags) ──────────────────
CONTROLLED_TAGS = [
    "coding", "billing", "denials", "prior_auth", "eligibility",
    "payment_posting", "claim_status", "compliance", "payer_policy",
    "credentialing", "patient_access", "general",
]


async def summarize_and_tag(content: str) -> tuple[str | None, list[str] | None]:
    """Use the platform LLM to produce a short summary + controlled topic tags.
    Best-effort: returns (None, None) if the LLM is unavailable or output is unusable."""
    text = (content or "")[:6000]
    if not text.strip():
        return None, None
    try:
        from src.core.nlp.ai_service import get_ai_service  # noqa: PLC0415
        backend = get_ai_service()._get_backend()
        system = (
            "You structure U.S. healthcare RCM reference material. "
            "Return ONLY JSON: {\"summary\": \"1-2 sentence summary\", \"tags\": [\"...\"]}. "
            "tags MUST be a subset of: " + ", ".join(CONTROLLED_TAGS) + "."
        )
        out, _ = await backend.call(system=system, user_content="Summarize and tag this reference:\n\n" + text,
                                    use_json=False, max_tokens=300)
        import json as _json, re as _re  # noqa: PLC0415
        m = _re.search(r"\{.*\}", out or "", _re.DOTALL)
        if not m:
            return None, None
        data = _json.loads(m.group(0))
        summary = (str(data.get("summary") or "")).strip() or None
        tags = [t for t in (data.get("tags") or []) if t in CONTROLLED_TAGS] or None
        return summary, tags
    except Exception as e:  # noqa: BLE001
        logger.warning("knowledge_autostructure_failed", error=str(e))
        return None, None


# ── File ingestion (PDF / DOCX / TXT / MD / CSV; image OCR optional) ─────────
def _is_readable(text: str) -> bool:
    """True if extracted text looks like real prose (not empty / glyph-code garbage)."""
    if not text or len(text.strip()) < 20:
        return False
    return len(re.findall(r"[A-Za-z]{3,}", text)) >= 20


def _ocr_image(data: bytes) -> str:
    import io  # noqa: PLC0415
    try:
        import pytesseract  # noqa: PLC0415
        from PIL import Image  # noqa: PLC0415
        txt = pytesseract.image_to_string(Image.open(io.BytesIO(data))).strip()
    except Exception as e:  # noqa: BLE001  (bad image, or tesseract binary missing)
        raise ValueError(f"Could not OCR the image: {e}")
    if not txt:
        raise ValueError("No text could be read from the image via OCR.")
    return txt


def _ocr_pdf(data: bytes) -> str:
    try:
        import pytesseract  # noqa: PLC0415
        from pdf2image import convert_from_bytes  # noqa: PLC0415
        pages = convert_from_bytes(data, dpi=200)
        txt = "\n".join(pytesseract.image_to_string(img) for img in pages).strip()
    except Exception as e:  # noqa: BLE001  (tesseract/poppler missing, or render error)
        raise ValueError(f"Could not OCR the PDF: {e}")
    if not txt:
        raise ValueError("No text could be extracted from the document, even with OCR.")
    return txt


def extract_text_from_file(filename: str, data: bytes) -> str:
    """Extract readable text from an uploaded file by extension."""
    import io  # noqa: PLC0415
    name = (filename or "").lower()
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    if ext == "pdf":
        import pypdf  # noqa: PLC0415
        reader = pypdf.PdfReader(io.BytesIO(data))
        text = "\n".join((pg.extract_text() or "") for pg in reader.pages).strip()
        if _is_readable(text):
            return text
        # Empty or glyph-code garbage (scanned, or custom subsetted fonts) -> OCR the pages.
        return _ocr_pdf(data)
    if ext == "docx":
        import docx  # noqa: PLC0415
        d = docx.Document(io.BytesIO(data))
        return "\n".join(par.text for par in d.paragraphs).strip()
    if ext in ("txt", "md", "csv", "tsv", "json", "text", ""):
        return data.decode("utf-8", "ignore").strip()
    if ext in ("png", "jpg", "jpeg", "gif", "webp", "bmp", "tiff"):
        return _ocr_image(data)
    try:
        return data.decode("utf-8").strip()
    except Exception:
        raise ValueError(f"Unsupported file type: .{ext}")


async def ingest_file(
    db: AsyncSession,
    *,
    practice_id: uuid.UUID | None,
    filename: str,
    data: bytes,
    added_by_id: uuid.UUID | None = None,
    tags: list | None = None,
    title: str | None = None,
) -> KnowledgeReference:
    """Extract text from an uploaded document and store it as a reference."""
    text = extract_text_from_file(filename, data)
    if not text:
        raise ValueError("No extractable text found in the file.")
    return await _store(
        db, practice_id=practice_id, title=(title or filename or "Uploaded document")[:300],
        url=None, source_type="file", content=text[:MAX_CONTENT_CHARS], added_by_id=added_by_id, tags=tags,
    )
