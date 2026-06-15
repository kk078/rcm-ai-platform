"""Real-time eligibility clearinghouse client (CAQH CORE / CMS HETS).

Vendor-agnostic: posts an X12 270 to a configured CAQH CORE-compliant endpoint and
parses the X12 271 response. CORE connectivity defines two envelopes — HTTP MIME and
SOAP+WSDL; this implements the HTTP/REST-style POST that CORE-compliant gateways
(and most commercial clearinghouses) accept. CMS HETS (Medicare) uses SOAP+MIME and
requires a Trading Partner Agreement + Submitter ID.

Configured entirely from settings; returns None (caller falls back to coverage-on-file)
when no clearinghouse is configured. This module never raises to the caller for network
errors — it returns a result dict with an "error" key so eligibility checks degrade
gracefully.

Ref: CAQH CORE Connectivity Rule vC2.2.0; CMS HETS 270/271 Companion Guide.
"""
from __future__ import annotations

import uuid
from datetime import date

import structlog

from .x12_270 import build_270
from .x12_271 import parse_271

logger = structlog.get_logger()

# CORE payload type for a real-time 270 request (005010X279A1).
CORE_PAYLOAD_TYPE = "X12_270_Request_005010X279A1"


def get_clearinghouse_settings(settings) -> dict | None:
    """Read clearinghouse config from settings; None if not fully configured."""
    url = getattr(settings, "clearinghouse_url", None)
    key = getattr(settings, "clearinghouse_api_key", None)
    if not url or not key:
        return None
    return {
        "url": url,
        "api_key": key,
        "sender_id": getattr(settings, "clearinghouse_sender_id", "AETHERA"),
        "receiver_id": getattr(settings, "clearinghouse_receiver_id", "CMS"),
        "timeout": float(getattr(settings, "clearinghouse_timeout_secs", 30) or 30),
    }


def is_configured(settings) -> bool:
    return get_clearinghouse_settings(settings) is not None


async def check_eligibility_271(
    settings,
    *,
    payer_name: str,
    payer_id: str,
    provider_last_or_org: str,
    provider_npi: str,
    subscriber_first: str,
    subscriber_last: str,
    member_id: str,
    subscriber_dob: date | None = None,
    service_date: date | None = None,
    service_type_code: str = "30",
) -> dict | None:
    """Build a 270, send it to the configured clearinghouse, and parse the 271.

    Returns the parse_271 dict (with a "_270"/"_271" raw echo), or a dict with an
    "error" key on failure, or None if no clearinghouse is configured.
    """
    cfg = get_clearinghouse_settings(settings)
    if cfg is None:
        return None

    payload_id = str(uuid.uuid4())
    x270 = build_270(
        sender_id=cfg["sender_id"],
        receiver_id=cfg["receiver_id"],
        payer_name=payer_name or "PAYER",
        payer_id=payer_id or "00000",
        provider_last_or_org=provider_last_or_org or "PROVIDER",
        provider_npi=provider_npi or "0000000000",
        subscriber_first=subscriber_first or "",
        subscriber_last=subscriber_last or "",
        member_id=member_id or "",
        subscriber_dob=subscriber_dob,
        service_date=service_date,
        service_type_code=service_type_code,
    )

    try:
        import httpx
    except ImportError:  # pragma: no cover
        return {"error": "httpx not available", "status": "error"}

    # CAQH CORE HTTP envelope (form fields). Commercial gateways accept this shape;
    # SOAP gateways/HETS wrap the same X12 in a SOAP body instead.
    form = {
        "PayloadType": CORE_PAYLOAD_TYPE,
        "ProcessingMode": "RealTime",
        "PayloadID": payload_id,
        "SenderID": cfg["sender_id"],
        "ReceiverID": cfg["receiver_id"],
        "CORERuleVersion": "2.2.0",
        "Payload": x270,
    }
    headers = {"Authorization": f"Bearer {cfg['api_key']}"}

    try:
        async with httpx.AsyncClient(timeout=cfg["timeout"]) as client:
            resp = await client.post(cfg["url"], data=form, headers=headers)
        if resp.status_code >= 400:
            logger.warning("clearinghouse_http_error", status=resp.status_code)
            return {"error": f"clearinghouse HTTP {resp.status_code}", "status": "error"}
        body = resp.text
        # The 271 may be the whole body or embedded in a CORE/SOAP envelope; isolate it.
        x271 = _extract_271(body)
        parsed = parse_271(x271)
        parsed["_271"] = x271[:4000]
        parsed["payload_id"] = payload_id
        return parsed
    except Exception as e:  # network/timeout/parse — degrade gracefully
        logger.warning("clearinghouse_request_failed", error=str(e))
        return {"error": str(e), "status": "error"}


def _extract_271(body: str) -> str:
    """Pull the X12 271 out of a CORE/SOAP response envelope if wrapped."""
    if not body:
        return ""
    idx = body.find("ISA")
    if idx == -1:
        return body  # assume the whole body is the 271 (or parse_271 will no-op)
    end = body.rfind("~")
    return body[idx:end + 1] if end > idx else body[idx:]
