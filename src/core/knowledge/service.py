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

    ref = KnowledgeReference(
        practice_id=practice_id, title=title, url=url, source_type=source_type,
        content=content, content_hash=chash, char_count=len(content),
        tags=tags, status="active", fetched_at=now, added_by_id=added_by_id,
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
