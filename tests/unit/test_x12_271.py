"""Unit tests for the X12 271 parser and 270 generator."""
from datetime import date

from src.core.eligibility.x12_271 import parse_271
from src.core.eligibility.x12_270 import build_270


def _seg(*fields):
    return "*".join(fields)


def _active_271():
    segs = [
        "ISA*00*          *00*          *ZZ*CMS            *ZZ*AETHERA        *260615*1200*^*00501*000000001*0*P*:",
        "GS*HB*CMS*AETHERA*20260615*1200*1*X*005010X279A1",
        "ST*271*0001*005010X279A1",
        "BHT*0022*11*000000001*20260615*1200",
        _seg("NM1", "PR", "2", "AETNA", "", "", "", "", "PI", "60054"),
        _seg("NM1", "IL", "1", "DOE", "JANE", "", "", "", "MI", "W123456789"),
        _seg("EB", "1", "", "30", "HM", "GOLD PLAN"),                  # active, HMO, plan name
        _seg("EB", "C", "IND", "30", "", "", "", "1500"),              # deductible 1500
        _seg("EB", "B", "IND", "30", "", "", "", "25"),                # copay 25
        _seg("EB", "A", "IND", "30", "", "", "", "", ".20"),           # coinsurance 20%
        _seg("EB", "1", "", "30", "", "", "", "", "", "", "", "", "Y"),  # EB12 = Y (in-network)
        "SE*16*0001",
        "GE*1*1",
        "IEA*1*000000001",
    ]
    return "~".join(segs) + "~"


class TestParse271:
    def test_active_coverage(self):
        r = parse_271(_active_271())
        assert r["status"] == "active"
        assert r["is_active"] is True

    def test_plan_type_from_eb04(self):
        assert parse_271(_active_271())["plan_type"] == "HMO"

    def test_plan_name(self):
        assert parse_271(_active_271())["plan_name"] == "GOLD PLAN"

    def test_benefits(self):
        r = parse_271(_active_271())
        assert r["deductible_total"] == 1500.0
        assert r["copay"] == 25.0
        assert r["coinsurance_pct"] == 20

    def test_network_status(self):
        assert parse_271(_active_271())["network_status"] == "in-network"

    def test_payer_and_member(self):
        r = parse_271(_active_271())
        assert r["payer_name"] == "AETNA"
        assert r["member_id"] == "W123456789"

    def test_inactive(self):
        segs = ["ST*271*0001*005010X279A1", _seg("EB", "6", "", "30")]
        r = parse_271("~".join(segs) + "~")
        assert r["status"] == "inactive"
        assert r["is_active"] is False

    def test_empty_payload(self):
        r = parse_271("")
        assert r["status"] == "unknown"
        assert "error" in r

    def test_medicare_code_mb(self):
        segs = ["ST*271*0001", _seg("EB", "1", "", "30", "MB")]
        assert parse_271("~".join(segs) + "~")["plan_type"] == "Medicare"


class TestBuild270:
    def test_envelopes_present(self):
        x = build_270(
            sender_id="AETHERA", receiver_id="CMS", payer_name="AETNA", payer_id="60054",
            provider_last_or_org="AETHERA HEALTH", provider_npi="1234567893",
            subscriber_first="JANE", subscriber_last="DOE", member_id="W123456789",
            subscriber_dob=date(1980, 5, 1), service_date=date(2026, 6, 15),
        )
        assert x.startswith("ISA*")
        assert x.rstrip().endswith("~")
        assert "ST*270*" in x
        assert "EQ*30~" in x
        assert "W123456789" in x
        assert "NM1*IL*1*DOE*JANE" in x
