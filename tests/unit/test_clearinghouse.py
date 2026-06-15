"""Unit tests for clearinghouse backends (HETS SOAP envelope, 271 extraction, config selection)."""
from types import SimpleNamespace

from src.core.eligibility.clearinghouse import (
    build_hets_soap_envelope,
    extract_271,
    get_clearinghouse_settings,
    is_configured,
    CORE_PAYLOAD_TYPE,
)


class TestHetsSoapEnvelope:
    def test_envelope_structure(self):
        env = build_hets_soap_envelope(
            "ISA*00*...~IEA*1*000000001~",
            sender_id="SUB12345", receiver_id="CMS",
            payload_id="abc-123", timestamp="2026-06-15T16:30:00Z",
        )
        assert "COREEnvelopeRealTimeRequest" in env
        assert f"<PayloadType>{CORE_PAYLOAD_TYPE}</PayloadType>" in env
        assert "<ProcessingMode>RealTime</ProcessingMode>" in env
        assert "<SenderID>SUB12345</SenderID>" in env
        assert "http://www.w3.org/2003/05/soap-envelope" in env
        assert "http://www.caqh.org/SOAP/WSDL/CORERule2.2.0.xsd" in env
        # 270 carried in CDATA
        assert "<![CDATA[ISA*00*...~IEA*1*000000001~]]>" in env


class TestExtract271:
    def test_extracts_from_soap_wrapped_body(self):
        x271 = "ISA*00*          *00*          *ZZ*CMS*ZZ*SUB*260615*1200*^*00501*1*0*P*:~ST*271*0001~SE*2*0001~IEA*1*1~"
        body = (
            '<soapenv:Envelope><soapenv:Body><cor:COREEnvelopeRealTimeResponse>'
            f'<Payload><![CDATA[{x271}]]></Payload>'
            '</cor:COREEnvelopeRealTimeResponse></soapenv:Body></soapenv:Envelope>'
        )
        assert extract_271(body) == x271

    def test_passthrough_when_no_isa(self):
        assert extract_271("no x12 here") == "no x12 here"

    def test_empty(self):
        assert extract_271("") == ""


class TestConfigSelection:
    def test_hets_soap_configured_with_url_and_key(self):
        s = SimpleNamespace(clearinghouse_provider="hets_soap",
                            clearinghouse_url="https://hets.cms.gov/soap",
                            clearinghouse_api_key="k")
        cfg = get_clearinghouse_settings(s)
        assert cfg is not None and cfg["provider"] == "hets_soap"

    def test_hets_soap_configured_with_client_cert_only(self):
        s = SimpleNamespace(clearinghouse_provider="hets_soap",
                            clearinghouse_url="https://hets.cms.gov/soap",
                            clearinghouse_api_key=None,
                            clearinghouse_client_cert="/certs/hets.pem")
        assert is_configured(s) is True

    def test_availity_requires_oauth_creds(self):
        incomplete = SimpleNamespace(clearinghouse_provider="availity",
                                     clearinghouse_url="https://api.availity.com/coverages",
                                     availity_client_id="id", availity_client_secret=None)
        assert get_clearinghouse_settings(incomplete) is None
        complete = SimpleNamespace(clearinghouse_provider="availity",
                                   clearinghouse_url="https://api.availity.com/coverages",
                                   availity_client_id="id", availity_client_secret="secret")
        cfg = get_clearinghouse_settings(complete)
        assert cfg is not None and cfg["provider"] == "availity"

    def test_unconfigured_returns_none(self):
        assert get_clearinghouse_settings(SimpleNamespace()) is None
