"""Unit tests for the plan-type taxonomy + X12 271 normalization."""
import pytest

from src.core.eligibility.plan_types import (
    PLAN_TYPES,
    normalize_plan_type,
    is_canonical_plan_type,
    validate_plan_type,
)


class TestNormalizeX12Codes:
    @pytest.mark.parametrize("code,expected", [
        ("MB", "Medicare"),   # Medicare Part B (the value found in the live DB)
        ("MA", "Medicare"),
        ("MP", "Medicare"),
        ("MC", "Medicaid"),
        ("QM", "Medicaid"),
        ("HM", "HMO"),
        ("HN", "HMO"),
        ("16", "HMO"),
        ("PR", "PPO"),
        ("12", "PPO"),
        ("PS", "POS"),
        ("13", "POS"),
        ("EP", "EPO"),
        ("14", "EPO"),
        ("IN", "Indemnity"),
        ("15", "Indemnity"),
        ("OT", "Other"),
    ])
    def test_x12_codes_map_to_canonical(self, code, expected):
        assert normalize_plan_type(code) == expected

    def test_x12_is_case_insensitive(self):
        assert normalize_plan_type("mb") == "Medicare"
        assert normalize_plan_type("hm") == "HMO"


class TestNormalizeFriendlyNames:
    @pytest.mark.parametrize("value,expected", [
        ("HMO", "HMO"),
        ("ppo", "PPO"),
        ("PoS", "POS"),
        ("EPO", "EPO"),
        ("IPA", "IPA"),
        ("Indemnity", "Indemnity"),
        ("HDHP", "HDHP"),
        ("Medicare", "Medicare"),
        ("Medicaid", "Medicaid"),
        ("Point of Service", "POS"),
        ("Health Maintenance Organization", "HMO"),
        ("Preferred Provider Organization", "PPO"),
        ("Independent Practice Association", "IPA"),
        ("Medicare Part B", "Medicare"),
        ("medicaid managed care", "Medicaid"),
    ])
    def test_friendly_names_map_to_canonical(self, value, expected):
        assert normalize_plan_type(value) == expected


class TestNormalizeEdgeCases:
    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_empty_returns_none(self, value):
        assert normalize_plan_type(value) is None

    @pytest.mark.parametrize("value", ["xyz", "BlueCross", "99", "ZZ"])
    def test_unknown_returns_none(self, value):
        assert normalize_plan_type(value) is None

    def test_whitespace_is_trimmed(self):
        assert normalize_plan_type("  PPO  ") == "PPO"


class TestCanonicalAndValidate:
    def test_all_canonical_values_normalize_to_themselves(self):
        for p in PLAN_TYPES:
            assert normalize_plan_type(p) == p

    def test_is_canonical(self):
        assert is_canonical_plan_type(None) is True
        assert is_canonical_plan_type("HMO") is True
        assert is_canonical_plan_type("MB") is False  # raw code is not canonical

    def test_validate_maps_known(self):
        assert validate_plan_type("MB") == "Medicare"
        assert validate_plan_type("") is None
        assert validate_plan_type(None) is None

    def test_validate_raises_on_unknown(self):
        with pytest.raises(ValueError):
            validate_plan_type("not-a-plan")

    def test_ipa_is_in_canonical_set(self):
        assert "IPA" in PLAN_TYPES
