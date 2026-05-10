"""Unit tests for the claim scrubbing rules engine."""

import pytest
from src.core.rules_engine.scrubber import ClaimScrubber, RuleSeverity, RuleType


@pytest.fixture
def scrubber():
    ncci_data = {
        "29881:29880": {"column1": "29881", "column2": "29880", "modifier_indicator": "1"},
        "99213:36415": {"column1": "99213", "column2": "36415", "modifier_indicator": "0"},
    }
    mue_data = {
        "99213": {"max_units": 1, "rationale": "E/M per encounter"},
        "36415": {"max_units": 3, "rationale": "Venipuncture"},
    }
    return ClaimScrubber(ncci_data=ncci_data, mue_data=mue_data)


class TestNCCIEdits:
    def test_bundled_codes_flagged(self, scrubber):
        claim = {
            "claim_id": "test-001",
            "claim_lines": [
                {"cpt_code": "99213", "modifiers": [], "units": 1},
                {"cpt_code": "36415", "modifiers": [], "units": 1},
            ],
            "diagnoses": [],
        }
        result = scrubber.scrub(claim)
        ncci_errors = [f for f in result.findings if f.rule_type == RuleType.NCCI_EDIT and f.severity == RuleSeverity.ERROR]
        assert len(ncci_errors) > 0
        assert not result.ready_to_submit

    def test_modifier_exception_allowed(self, scrubber):
        claim = {
            "claim_id": "test-002",
            "claim_lines": [
                {"cpt_code": "29881", "modifiers": [], "units": 1},
                {"cpt_code": "29880", "modifiers": ["59"], "units": 1},
            ],
            "diagnoses": [],
        }
        result = scrubber.scrub(claim)
        ncci_errors = [f for f in result.findings if f.rule_type == RuleType.NCCI_EDIT and f.severity == RuleSeverity.ERROR]
        assert len(ncci_errors) == 0


class TestMUE:
    def test_excess_units_flagged(self, scrubber):
        claim = {
            "claim_id": "test-003",
            "claim_lines": [
                {"cpt_code": "99213", "modifiers": [], "units": 3},
            ],
            "diagnoses": [],
        }
        result = scrubber.scrub(claim)
        mue_errors = [f for f in result.findings if f.rule_type == RuleType.MUE]
        assert len(mue_errors) > 0

    def test_valid_units_pass(self, scrubber):
        claim = {
            "claim_id": "test-004",
            "claim_lines": [
                {"cpt_code": "36415", "modifiers": [], "units": 2},
            ],
            "diagnoses": [],
        }
        result = scrubber.scrub(claim)
        mue_errors = [f for f in result.findings if f.rule_type == RuleType.MUE]
        assert len(mue_errors) == 0


class TestModifiers:
    def test_conflicting_modifiers_flagged(self, scrubber):
        claim = {
            "claim_id": "test-005",
            "claim_lines": [
                {"cpt_code": "71046", "modifiers": ["26", "TC"], "units": 1},
            ],
            "diagnoses": [],
        }
        result = scrubber.scrub(claim)
        mod_errors = [f for f in result.findings if f.rule_type == RuleType.MODIFIER and f.severity == RuleSeverity.ERROR]
        assert len(mod_errors) > 0


class TestScoring:
    def test_clean_claim_high_score(self, scrubber):
        claim = {
            "claim_id": "test-006",
            "claim_lines": [
                {"cpt_code": "36415", "modifiers": [], "units": 1, "icd_pointers": ["J06.9"]},
            ],
            "diagnoses": ["J06.9"],
        }
        result = scrubber.scrub(claim)
        assert result.score >= 80

    def test_multiple_errors_low_score(self, scrubber):
        claim = {
            "claim_id": "test-007",
            "claim_lines": [
                {"cpt_code": "99213", "modifiers": ["26", "TC"], "units": 5},
                {"cpt_code": "36415", "modifiers": [], "units": 1},
            ],
            "diagnoses": [],
        }
        result = scrubber.scrub(claim)
        assert result.score < 50
