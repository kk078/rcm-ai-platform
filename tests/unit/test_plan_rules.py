"""Unit tests for plan-type business rules (referral / OON / delegated billing)."""
from src.core.eligibility.plan_rules import (
    evaluate_plan_type_rules,
    get_plan_rule,
)


def _codes(findings):
    return {f.code for f in findings}


class TestOutOfNetwork:
    def test_hmo_oon_not_covered_is_error(self):
        f = evaluate_plan_type_rules(plan_type="HMO", network_status="out-of-network")
        assert "PLAN_OON_NOT_COVERED" in _codes(f)
        assert any(x.severity == "error" for x in f)

    def test_epo_oon_not_covered(self):
        assert "PLAN_OON_NOT_COVERED" in _codes(
            evaluate_plan_type_rules(plan_type="EPO", network_status="out-of-network")
        )

    def test_hmo_oon_emergency_pos23_is_allowed(self):
        f = evaluate_plan_type_rules(plan_type="HMO", network_status="out-of-network", place_of_service="23")
        assert "PLAN_OON_NOT_COVERED" not in _codes(f)

    def test_ppo_oon_is_info_higher_cost(self):
        f = evaluate_plan_type_rules(plan_type="PPO", network_status="out-of-network")
        assert "PLAN_OON_HIGHER_COST" in _codes(f)
        assert "PLAN_OON_NOT_COVERED" not in _codes(f)

    def test_in_network_no_oon_finding(self):
        f = evaluate_plan_type_rules(plan_type="HMO", network_status="in-network")
        assert "PLAN_OON_NOT_COVERED" not in _codes(f)
        assert "PLAN_OON_HIGHER_COST" not in _codes(f)


class TestReferral:
    def test_hmo_specialist_without_referral_warns(self):
        f = evaluate_plan_type_rules(plan_type="HMO", is_specialist=True, referral_on_file=False)
        assert "PLAN_REFERRAL_REQUIRED" in _codes(f)

    def test_ppo_specialist_without_referral_ok(self):
        f = evaluate_plan_type_rules(plan_type="PPO", is_specialist=True, referral_on_file=False)
        assert "PLAN_REFERRAL_REQUIRED" not in _codes(f)

    def test_hmo_with_referral_ok(self):
        f = evaluate_plan_type_rules(plan_type="HMO", is_specialist=True, referral_on_file=True)
        assert "PLAN_REFERRAL_REQUIRED" not in _codes(f)


class TestDelegatedAndUnknown:
    def test_ipa_flags_delegated_billing(self):
        assert "PLAN_DELEGATED_BILLING" in _codes(evaluate_plan_type_rules(plan_type="IPA"))

    def test_unknown_plan_type_no_findings(self):
        assert evaluate_plan_type_rules(plan_type="something-weird") == []
        assert evaluate_plan_type_rules(plan_type=None) == []

    def test_get_plan_rule_accepts_x12_code(self):
        rule = get_plan_rule("MB")  # MB -> Medicare
        assert rule is not None and rule.covers_out_of_network is True
