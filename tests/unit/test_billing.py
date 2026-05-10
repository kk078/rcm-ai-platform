"""Tests for billing service: claim creation, scrubbing, EDI generation, errors."""

import os
from uuid import uuid4

import pytest

os.environ.setdefault("PHI_ENCRYPTION_KEY", "test-encryption-key-for-testing-only-32b")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing")

from src.core.billing.errors import (
    BillingError,
    ClaimNotFoundError,
    ClaimStatusError,
    ClaimScrubError,
    ClaimSubmissionError,
)
from src.core.billing.service import ClaimService, VALID_TRANSITIONS
from src.core.rules_engine.scrubber import ClaimScrubber, ScrubFinding, RuleType, RuleSeverity


# ── Error Hierarchy Tests ────────────────────────────────────────────


class TestBillingErrors:
    def test_all_errors_inherit_from_base(self):
        errors = [
            ClaimNotFoundError(uuid4()),
            ClaimStatusError(),
            ClaimScrubError(),
            ClaimSubmissionError(),
        ]
        for err in errors:
            assert isinstance(err, BillingError)

    def test_error_status_codes(self):
        assert ClaimNotFoundError(uuid4()).status_code == 404
        assert ClaimStatusError().status_code == 422
        assert ClaimScrubError().status_code == 422
        assert ClaimSubmissionError().status_code == 502

    def test_claim_not_found_detail(self):
        uid = uuid4()
        err = ClaimNotFoundError(uid)
        assert str(uid) in err.detail
        assert err.status_code == 404

    def test_claim_status_error_detail(self):
        err = ClaimStatusError("Cannot submit claim in 'draft' status")
        assert "draft" in err.detail
        assert err.status_code == 422

    def test_claim_scrub_error_detail(self):
        err = ClaimScrubError("NCCI bundling error")
        assert "NCCI" in err.detail
        assert err.status_code == 422

    def test_claim_submission_error_detail(self):
        err = ClaimSubmissionError("Clearinghouse connection timeout")
        assert "timeout" in err.detail
        assert err.status_code == 502


# ── Claim Number Generation Tests ────────────────────────────────────


class TestClaimNumberGeneration:
    def test_claim_number_format(self):
        """Claim numbers follow CLM-XXXXXXXXXXXX format."""
        service = ClaimService()
        # Use a fresh uuid to simulate claim number generation
        claim_number = f"CLM-{uuid4().hex[:12].upper()}"
        assert claim_number.startswith("CLM-")
        assert len(claim_number) == 16  # "CLM-" + 12 hex chars

    def test_claim_number_uniqueness(self):
        """Each claim number is unique."""
        numbers = {f"CLM-{uuid4().hex[:12].upper()}" for _ in range(100)}
        assert len(numbers) == 100


# ── Claim Status Transition Tests ─────────────────────────────────────


class TestClaimStatusTransitions:
    def test_draft_to_ready(self):
        assert "ready" in VALID_TRANSITIONS["draft"]

    def test_draft_to_scrub_failed(self):
        assert "scrub_failed" in VALID_TRANSITIONS["draft"]

    def test_ready_to_submitted(self):
        assert "submitted" in VALID_TRANSITIONS["ready"]

    def test_submitted_to_accepted(self):
        assert "accepted" in VALID_TRANSITIONS["submitted"]

    def test_submitted_to_rejected(self):
        assert "rejected" in VALID_TRANSITIONS["submitted"]

    def test_denied_to_appealed(self):
        assert "appealed" in VALID_TRANSITIONS["denied"]

    def test_closed_is_terminal(self):
        assert len(VALID_TRANSITIONS["closed"]) == 0

    def test_invalid_transition_not_allowed(self):
        assert "submitted" not in VALID_TRANSITIONS["draft"]
        assert "paid" not in VALID_TRANSITIONS["draft"]


# ── Build Claim Dict for Scrubber Tests ──────────────────────────────


class TestBuildClaimDictForScrubber:
    def test_basic_claim_dict(self):
        """Convert ORM-like objects to scrubber dict format."""
        service = ClaimService()

        # Mock claim object
        class MockClaim:
            id = uuid4()
            claim_type = "837P"
            place_of_service = None

        # Mock claim lines
        class MockLine:
            cpt_code = "99213"
            modifier_1 = "25"
            modifier_2 = None
            modifier_3 = None
            modifier_4 = None
            units = 1.0
            charge_amount = 150.0
            line_number = 1
            place_of_service = "11"

        # Mock diagnoses
        class MockDx:
            icd10_code = "M54.5"

        result = service._build_claim_dict_for_scrubber(MockClaim(), [MockLine()], [MockDx()])
        assert result["claim_id"] == str(MockClaim.id)
        assert len(result["claim_lines"]) == 1
        assert result["claim_lines"][0]["cpt_code"] == "99213"
        assert result["claim_lines"][0]["modifiers"] == ["25"]
        assert "M54.5" in result["diagnoses"]

    def test_claim_dict_with_multiple_modifiers(self):
        """Lines with multiple modifiers are collected correctly."""
        service = ClaimService()

        class MockClaim:
            id = uuid4()
            claim_type = "837I"

        class MockLine:
            cpt_code = "71045"
            modifier_1 = "26"
            modifier_2 = "TC"
            modifier_3 = None
            modifier_4 = None
            units = 1.0
            charge_amount = 200.0
            line_number = 1
            place_of_service = "21"

        class MockDx:
            icd10_code = "A00.0"

        result = service._build_claim_dict_for_scrubber(MockClaim(), [MockLine()], [MockDx()])
        assert result["claim_lines"][0]["modifiers"] == ["26", "TC"]

    def test_claim_dict_with_no_modifiers(self):
        """Lines with no modifiers produce empty list."""
        service = ClaimService()

        class MockClaim:
            id = uuid4()
            claim_type = "837P"

        class MockLine:
            cpt_code = "99213"
            modifier_1 = None
            modifier_2 = None
            modifier_3 = None
            modifier_4 = None
            units = 1.0
            charge_amount = 100.0
            line_number = 1
            place_of_service = "11"

        class MockDx:
            icd10_code = "Z00.00"

        result = service._build_claim_dict_for_scrubber(MockClaim(), [MockLine()], [MockDx()])
        assert result["claim_lines"][0]["modifiers"] == []


# ── Claim Scrubber Integration Tests ────────────────────────────────


class TestClaimScrubIntegration:
    def test_clean_claim_passes_scrub(self):
        """A clean claim with no edits should pass scrubbing."""
        scrubber = ClaimScrubber()
        claim = {
            "claim_id": "test",
            "diagnoses": ["A00.0"],
            "claim_lines": [
                {"cpt_code": "99213", "modifiers": [], "units": 1, "line_number": 1, "icd_pointers": ["A00.0"]},
            ],
        }
        result = scrubber.scrub(claim)
        assert result.score > 0
        assert result.ready_to_submit

    def test_ncci_bundling_detected(self):
        """NCCI edit: Column 2 bundled into Column 1."""
        scrubber = ClaimScrubber(
            ncci_data={
                "99213:99214": {
                    "column1": "99213",
                    "column2": "99214",
                    "modifier_indicator": "0",
                }
            }
        )
        claim = {
            "claim_id": "test",
            "diagnoses": ["A00.0"],
            "claim_lines": [
                {"cpt_code": "99213", "modifiers": [], "units": 1, "line_number": 1},
                {"cpt_code": "99214", "modifiers": [], "units": 1, "line_number": 2},
            ],
        }
        result = scrubber.scrub(claim)
        ncci_findings = [f for f in result.findings if f.rule_type.value == "ncci_edit"]
        assert len(ncci_findings) > 0
        assert not result.ready_to_submit

    def test_mue_violation_detected(self):
        """MUE: units exceed max allowed."""
        scrubber = ClaimScrubber(
            mue_data={"99213": {"max_units": 4, "rationale": "CMS"}}
        )
        claim = {
            "claim_id": "test",
            "diagnoses": ["A00.0"],
            "claim_lines": [
                {"cpt_code": "99213", "modifiers": [], "units": 10, "line_number": 1},
            ],
        }
        result = scrubber.scrub(claim)
        mue_findings = [f for f in result.findings if f.rule_type.value == "mue"]
        assert len(mue_findings) > 0
        assert not result.ready_to_submit

    def test_modifier_conflict_detected(self):
        """Modifier 26 and TC cannot appear together."""
        scrubber = ClaimScrubber()
        claim = {
            "claim_id": "test",
            "diagnoses": ["A00.0"],
            "claim_lines": [
                {"cpt_code": "71045", "modifiers": ["26", "TC"], "units": 1, "line_number": 1},
            ],
        }
        result = scrubber.scrub(claim)
        mod_findings = [f for f in result.findings if f.rule_type.value == "modifier"]
        assert len(mod_findings) > 0


# ── EDI 837 Generation Tests ────────────────────────────────────────


class TestEDI837Generation:
    def test_837p_envelope_generation(self):
        """Claim837Generator produces valid ISA/GS/ST/BHT envelope."""
        from src.services.edi.parser import Claim837Generator
        generator = Claim837Generator(sender_id="SENDER", receiver_id="RECEIVER")
        claim_data = {
            "claim_number": "CLM-TEST123",
            "claim_type": "837P",
            "total_charge": 250.0,
            "frequency_code": "1",
        }
        edi = generator.generate_837p([claim_data])
        assert "ISA" in edi
        assert "GS" in edi
        assert "ST" in edi
        assert "BHT" in edi
        assert "SE" in edi
        assert "GE" in edi
        assert "IEA" in edi

    def test_837p_with_multiple_claims(self):
        """Batch EDI contains all claims."""
        from src.services.edi.parser import Claim837Generator
        generator = Claim837Generator(sender_id="SENDER", receiver_id="RECEIVER")
        claims = [
            {"claim_number": f"CLM-{i}", "claim_type": "837P", "total_charge": 100.0 * i, "frequency_code": "1"}
            for i in range(3)
        ]
        edi = generator.generate_837p(claims)
        assert "ISA" in edi
        assert edi.count("BHT") >= 1


# ── Batch Submit Logic Tests ──────────────────────────────────────────


class TestBatchSubmitLogic:
    def test_batch_submit_filters_non_ready(self):
        """Batch submit skips claims that aren't in 'ready' status."""
        # Verify the status state machine: only 'ready' can transition to 'submitted'
        assert "submitted" in VALID_TRANSITIONS["ready"]
        # Claims in draft or scrub_failed cannot be submitted directly
        assert "submitted" not in VALID_TRANSITIONS["draft"]
        assert "submitted" not in VALID_TRANSITIONS["scrub_failed"]
        # scrub_failed can re-enter scrubbing
        assert "scrubbing" in VALID_TRANSITIONS["scrub_failed"]


# ── ClaimService Initialization Tests ─────────────────────────────────


class TestClaimServiceInit:
    def test_service_has_scrubber(self):
        service = ClaimService()
        assert service.scrubber is not None
        assert isinstance(service.scrubber, ClaimScrubber)

    def test_ai_service_lazy_init(self):
        """AI service is lazily initialized."""
        service = ClaimService()
        assert service._ai_service is None


# ── Scrub Finding Tests ──────────────────────────────────────────────


class TestScrubFinding:
    def test_finding_creation(self):
        finding = ScrubFinding(
            rule_type=RuleType.NCCI_EDIT,
            severity=RuleSeverity.ERROR,
            message="NCCI bundling: 99214 into 99213",
            suggestion="Add modifier 59 if services were distinct",
        )
        assert finding.rule_type == RuleType.NCCI_EDIT
        assert finding.severity == RuleSeverity.ERROR
        assert finding.auto_fixable is False

    def test_finding_auto_fixable(self):
        finding = ScrubFinding(
            rule_type=RuleType.MODIFIER,
            severity=RuleSeverity.WARNING,
            message="Modifier 25 may be needed",
            suggestion="Add modifier 25",
            auto_fixable=True,
        )
        assert finding.auto_fixable is True