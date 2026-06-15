"""Real-time eligibility clearinghouse client — pluggable backends.

Backends (settings.clearinghouse_provider):
  - "core_http" (default): CAQH CORE HTTP/MIME form POST of the 270 (commercial gateways).
  - "hets_soap": CMS HETS (Medicare) — SOAP 1.2 COREEnvelopeRealTimeRequest (CAQH CORE vC2.2.0),
        270 carried in a CDATA Payload, SenderID = the CMS-assigned Submitter ID. HETS requires a
        Trading Partner Agreement + Submitter ID and (typically) a client digital certificate (mTLS).
  - "availity": Availity REST — OAuth2 client-credentials token, then the 270 sent with the
        provider's NPI / Tax ID (TIN) / TAN, which Availity requires per request.

All backends build the same X12 270 and parse the X12 271 out of the response. The module never
raises to the caller for transport errors — it returns a dict with an "error" key so eligibility
degrades gracefully to coverage-on-file.

Refs: CMS HETS 270/271 SOAP/MIME Connectivity Guide; CAQH CORE Connectivity Rule vC2.2.0;
Availity API Guide (OAuth2 client credentials; provider NPI/TIN required).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import structlog

from .x12_270 import build_270
from .x12_271 import parse_271

logger = structlog.get_logger()

CORE_PAYLOAD_TYPE = "X12_270_Request_005010X279A1"
CORE_RULE_VERSION = "2.2.0"
SOAP_NS = "http://www.w3.org/2003/05/soap-envelope"
CORE_NS = "http://www.caqh.org/SOAP/WSDL/CORERule2.2.0.xsd"


def get_clearinghouse_settings(settings) -> dict | None:
    """Read clearinghouse config; None if the selected provider isn't fully configured."""
    provider = (getattr(settings, "clearinghouse_provider", None) or "core_http").lower()
    cfg = {
        "provider": provider,
        "url": getattr(settings, "clearinghouse_url", None),
        "api_key": getattr(settings, "clearinghouse_api_key", None),
        "sender_id": getattr(settings, "clearinghouse_sender_id", "AETHERA"),
        "receiver_id": getattr(settings, "clearinghouse_receiver_id", "CMS"),
        "timeout": float(getattr(settings, "clearinghouse_timeout_secs", 30) or 30),
        "client_cert": getattr(settings, "clearinghouse_client_cert", None),  # mTLS for HETS (path or (cert,key))
        "provider_npi": getattr(settings, "clearinghouse_provider_npi", None),
        "provider_tin": getattr(settings, "clearinghouse_provider_tin", None),
        "provider_tan": getattr(settings, "clearinghouse_provider_tan", None),
        "availity_client_id": getattr(settings, "availity_client_id", None),
        "availity_client_secret": getattr(settings, "availity_client_secret", None),
        "availity_token_url": getattr(settings, "availity_token_url",
                                       "https://api.availity.com/availity/v1/token"),
    }
    if provider == "availity":
        if cfg["url"] and cfg["availity_client_id"] and cfg["availity_client_secret"]:
            return cfg
        return None
    # core_http / hets_soap need an endpoint + api key (HETS may also use a client cert)
    if cfg["url"] and (cfg["api_key"] or cfg["client_cert"]):
        return cfg
    return None


def is_configured(settings) -> bool:
    return get_clearinghouse_settings(settings) is not None


def build_hets_soap_envelope(x270: str, *, sender_id: str, receiver_id: str,
                             payload_id: str, timestamp: str) -> str:
    """CMS HETS / CAQH CORE vC2.2.0 SOAP 1.2 real-time request envelope."""
    return (
        f'<soapenv:Envelope xmlns:soapenv="{SOAP_NS}" xmlns:cor="{CORE_NS}">'
        "<soapenv:Header/>"
        "<soapenv:Body>"
        "<cor:COREEnvelopeRealTimeRequest>"
        f"<PayloadType>{CORE_PAYLOAD_TYPE}</PayloadType>"
        "<ProcessingMode>RealTime</ProcessingMode>"
        f"<PayloadID>{payload_id}</PayloadID>"
        f"<TimeStamp>{timestamp}</TimeStamp>"
        f"<SenderID>{sender_id}</SenderID>"
        f"<ReceiverID>{receiver_id}</ReceiverID>"
        f"<CORERuleVersion>{CORE_RULE_VERSION}</CORERuleVersion>"
        f"<Payload><![CDATA[{x270}]]></Payload>"
        "</cor:COREEnvelopeRealTimeRequest>"
        "</soapenv:Body>"
        "</soapenv:Envelope>"
    )


def extract_271(body: str) -> str:
    """Pull the X12 271 out of a CORE/SOAP/MIME response envelope (or return as-is)."""
    if not body:
        return ""
    idx = body.find("ISA")
    if idx == -1:
        return body
    end = body.rfind("~")
    return body[idx:end + 1] if end > idx else body[idx:]


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
    """Build a 270, send it via the configured backend, and parse the 271.
    Returns parse_271 dict (with payload_id/_271), a {"error":...} dict, or None if unconfigured."""
    cfg = get_clearinghouse_settings(settings)
    if cfg is None:
        return None

    payload_id = str(uuid.uuid4())
    # Prefer an explicitly configured billing NPI for the inquiry, else the caller's.
    npi = cfg.get("provider_npi") or provider_npi
    x270 = build_270(
        sender_id=cfg["sender_id"], receiver_id=cfg["receiver_id"],
        payer_name=payer_name or "PAYER", payer_id=payer_id or "00000",
        provider_last_or_org=provider_last_or_org or "PROVIDER", provider_npi=npi or "0000000000",
        subscriber_first=subscriber_first or "", subscriber_last=subscriber_last or "",
        member_id=member_id or "", subscriber_dob=subscriber_dob,
        service_date=service_date, service_type_code=service_type_code,
    )

    try:
        import httpx
    except ImportError:  # pragma: no cover
        return {"error": "httpx not available", "status": "error"}

    try:
        if cfg["provider"] == "hets_soap":
            body = await _send_hets_soap(httpx, cfg, x270, payload_id)
        elif cfg["provider"] == "availity":
            body = await _send_availity(httpx, cfg, x270)
        else:
            body = await _send_core_http(httpx, cfg, x270, payload_id)
    except Exception as e:  # transport/timeout/auth — degrade gracefully
        logger.warning("clearinghouse_request_failed", provider=cfg["provider"], error=str(e))
        return {"error": str(e), "status": "error"}

    x271 = extract_271(body)
    parsed = parse_271(x271)
    parsed["_271"] = x271[:4000]
    parsed["payload_id"] = payload_id
    parsed["clearinghouse"] = cfg["provider"]
    return parsed


async def _send_core_http(httpx, cfg: dict, x270: str, payload_id: str) -> str:
    form = {
        "PayloadType": CORE_PAYLOAD_TYPE, "ProcessingMode": "RealTime", "PayloadID": payload_id,
        "SenderID": cfg["sender_id"], "ReceiverID": cfg["receiver_id"],
        "CORERuleVersion": CORE_RULE_VERSION, "Payload": x270,
    }
    headers = {"Authorization": f"Bearer {cfg['api_key']}"} if cfg.get("api_key") else {}
    async with httpx.AsyncClient(timeout=cfg["timeout"]) as client:
        resp = await client.post(cfg["url"], data=form, headers=headers)
    resp.raise_for_status()
    return resp.text


async def _send_hets_soap(httpx, cfg: dict, x270: str, payload_id: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    envelope = build_hets_soap_envelope(
        x270, sender_id=cfg["sender_id"], receiver_id=cfg["receiver_id"],
        payload_id=payload_id, timestamp=ts,
    )
    headers = {"Content-Type": "application/soap+xml; charset=utf-8"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    # HETS commonly requires a client digital certificate (mTLS).
    client_kwargs = {"timeout": cfg["timeout"]}
    if cfg.get("client_cert"):
        client_kwargs["cert"] = cfg["client_cert"]
    async with httpx.AsyncClient(**client_kwargs) as client:
        resp = await client.post(cfg["url"], content=envelope.encode("utf-8"), headers=headers)
    resp.raise_for_status()
    return resp.text


async def _send_availity(httpx, cfg: dict, x270: str) -> str:
    # 1) OAuth2 client-credentials token
    async with httpx.AsyncClient(timeout=cfg["timeout"]) as client:
        tok = await client.post(cfg["availity_token_url"], data={
            "grant_type": "client_credentials",
            "client_id": cfg["availity_client_id"],
            "client_secret": cfg["availity_client_secret"],
            "scope": "hipaa",
        })
        tok.raise_for_status()
        access_token = tok.json().get("access_token")
        # 2) Submit the 270 with the provider's identifiers (NPI / Tax ID / TAN).
        #    Field names per Availity's HIPAA-transaction / coverages API; adjust to the
        #    current Availity developer spec for your organization.
        payload = {
            "payload": x270,
            "providerNpi": cfg.get("provider_npi") or "",
            "providerTaxId": cfg.get("provider_tin") or "",
            "tradingPartnerServiceId": cfg.get("provider_tan") or cfg.get("receiver_id") or "",
        }
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        resp = await client.post(cfg["url"], json=payload, headers=headers)
        resp.raise_for_status()
        return resp.text
