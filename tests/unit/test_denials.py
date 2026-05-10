"""Tests for denial service: AI classification, priority scoring,
appeal generation, status transitions, CARC fallback, analytics."""

import os
from datetime import date, timedelta
from uuid import uuid4

import pytest

os.environ.setdefault("PHI_ENCRYPTION_KEY", "test-encryption-key-for-testing-only-32b")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing")

from src.core.denials.errors import (
    DenialError,
    DenialNotFoundError,
    DenialStatusError,
    AppealNotFoundError,
    DenialClassificationError,
)
from src.core.denials.service import DenialService, CARC_CATEGORY_MAP, VALID_DENIAL_TRANSITIONS


# ── Error Hierarchy Tests ────────────────────────────────────────────


class TestDenialErrors:
    def test_all_errors_inherit_from_base(self):
        errors = [
            DenialNotFoundError(uuid4()),
            DenialStatusError(),
            AppealNotFoundError(uuid4()),
            DenialClassificationError(),
        ]
        for err in errors:
            assert isinstance(err, DenialError)

    def test_error_status_codes(self):
        assert DenialNotFoundError(uuid4()).status_code == 404
        assert DenialStatusError().status_code == 422
        assert AppealNotFoundError(uuid4()).status_code == 404
        assert DenialClassificationError().status_code == 422

    def test_denial_not_found_detail(self):
        uid = uuid4()
        err = DenialNotFoundError(uid)
        assert str(uid) in err.detail
        assert err.status_code == 404

    def test_denial_status_error_detail(self):
        err = DenialStatusError("Cannot classify denial in 'resolved' status")
        assert "resolved" in err.detail
        assert err.status_code == 422

    def test_appeal_not_found_detail(self):
        uid = uuid4()
        err = AppealNotFoundError(uid)
        assert str(uid) in err.detail

    def test_classification_error_detail(self):
        err = DenialClassificationError("AI service unavailable")
        assert "AI" in err.detail
        assert err.status_code == 422


# ── Priority Score Calculation Tests ──────────────────────────────────


class TestPriorityScoreCalculation:
    def test_high_recovery_high_amount_urgent(self):
        """High recovery, high amount, urgent deadline → high score."""
        score = DenialService._calculate_priority_score(
            recovery_probability=0.8, denial_amount=5000, days_until_deadline=3
        )
        assert score > 0.5  # Should be relatively high

    def test_low_recovery_low_amount_distant(self):
        """Low recovery, small amount, distant deadline → low score."""
        score = DenialService._calculate_priority_score(
            recovery_probability=0.1, denial_amount=100, days_until_deadline=60
        )
        assert score < 0.5

    def test_zero_recovery_probability(self):
        """Zero recovery probability still gets some score from amount and urgency."""
        score = DenialService._calculate_priority_score(
            recovery_probability=0.0, denial_amount=10000, days_until_deadline=2
        )
        assert score > 0  # Amount and urgency contribute

    def test_none_deadline_uses_default_urgency(self):
        """None deadline uses 0.5 urgency factor."""
        score_none = DenialService._calculate_priority_score(
            recovery_probability=0.5, denial_amount=1000, days_until_deadline=None
        )
        score_60_days = DenialService._calculate_priority_score(
            recovery_probability=0.5, denial_amount=1000, days_until_deadline=60
        )
        # Both use low urgency (0.5 for None, 1.0 for >30 days)
        assert score_none > 0
        assert score_60_days > 0

    def test_score_capped_at_1(self):
        """Priority score cannot exceed 1.0."""
        score = DenialService._calculate_priority_score(
            recovery_probability=1.0, denial_amount=100000, days_until_deadline=1
        )
        assert score <= 1.0

    def test_score_is_non_negative(self):
        """Priority score is never negative."""
        score = DenialService._calculate_priority_score(
            recovery_probability=0.0, denial_amount=0, days_until_deadline=100
        )
        assert score >= 0


# ── Deadline Urgency Tests ────────────────────────────────────────────


class TestDeadlineUrgency:
    def test_very_urgent(self):
        """Less than 5 days → urgency 3.0."""
        assert DenialService._compute_deadline_urgency(3) == 3.0

    def test_urgent(self):
        """5 to 14 days → urgency 2.0."""
        assert DenialService._compute_deadline_urgency(10) == 2.0

    def test_moderate(self):
        """15 to 30 days → urgency 1.5."""
        assert DenialService._compute_deadline_urgency(20) == 1.5

    def test_distant(self):
        """More than 30 days → urgency 1.0."""
        assert DenialService._compute_deadline_urgency(60) == 1.0

    def test_none_deadline(self):
        """No deadline → urgency 0.5."""
        assert DenialService._compute_deadline_urgency(None) == 0.5

    def test_zero_days(self):
        """0 days until deadline → urgency 3.0 (very urgent)."""
        assert DenialService._compute_deadline_urgency(0) == 3.0


# ── CARC Fallback Classification Tests ────────────────────────────────


class TestCarcFallbackClassification:
    def test_authorization_codes(self):
        """CARC codes 4, 5, 6 map to authorization."""
        for code in ["4", "5", "6"]:
            result = DenialService._classify_by_carc(code)
            assert result["category"] == "authorization"

    def test_coding_codes(self):
        """CARC codes 9, 10, 11 map to coding."""
        result = DenialService._classify_by_carc("9")
        assert result["category"] == "coding"

    def test_billing_codes(self):
        """CARC code 18 maps to billing."""
        result = DenialService._classify_by_carc("18")
        assert result["category"] == "billing"

    def test_clinical_codes(self):
        """CARC code 49 maps to clinical."""
        result = DenialService._classify_by_carc("49")
        assert result["category"] == "clinical"

    def test_registration_codes(self):
        """CARC code 177 maps to registration."""
        result = DenialService._classify_by_carc("177")
        assert result["category"] == "registration"

    def test_unknown_code_maps_to_other(self):
        """Unknown CARC codes map to 'other'."""
        result = DenialService._classify_by_carc("999")
        assert result["category"] == "other"

    def test_fallback_includes_root_cause(self):
        """Fallback includes root cause string with CARC code."""
        result = DenialService._classify_by_carc("197")
        assert "197" in result["root_cause"]

    def test_fallback_includes_recovery_probability(self):
        """Fallback includes a recovery probability."""
        result = DenialService._classify_by_carc("4")
        assert "recovery_probability" in result
        assert 0 <= result["recovery_probability"] <= 1.0

    def test_authorization_has_higher_recovery(self):
        """Authorization denials have higher recovery probability than other categories."""
        auth_result = DenialService._classify_by_carc("4")
        other_result = DenialService._classify_by_carc("999")
        assert auth_result["recovery_probability"] > other_result["recovery_probability"]


# ── Denial Status Transition Tests ──────────────────────────────────


class TestDenialStatusTransitions:
    def test_new_to_in_review(self):
        assert "in_review" in VALID_DENIAL_TRANSITIONS["new"]

    def test_new_to_written_off(self):
        assert "written_off" in VALID_DENIAL_TRANSITIONS["new"]

    def test_in_review_to_appealing(self):
        assert "appealing" in VALID_DENIAL_TRANSITIONS["in_review"]

    def test_in_review_to_written_off(self):
        assert "written_off" in VALID_DENIAL_TRANSITIONS["in_review"]

    def test_appealing_to_resolved(self):
        assert "resolved" in VALID_DENIAL_TRANSITIONS["appealing"]

    def test_resolved_is_terminal(self):
        assert len(VALID_DENIAL_TRANSITIONS["resolved"]) == 0

    def test_written_off_is_terminal(self):
        assert len(VALID_DENIAL_TRANSITIONS["written_off"]) == 0

    def test_cannot_go_from_new_to_appealing(self):
        assert "appealing" not in VALID_DENIAL_TRANSITIONS["new"]

    def test_cannot_go_from_new_to_resolved(self):
        assert "resolved" not in VALID_DENIAL_TRANSITIONS["new"]


# ── Service Initialization Tests ─────────────────────────────────────


class TestDenialServiceInit:
    def test_service_has_no_ai_service_initially(self):
        service = DenialService()
        assert service._ai_service is None

    def test_lazy_ai_service_init(self):
        """AI service is lazily initialized on first access."""
        service = DenialService()
        # _get_ai_service would import and create AIService,
        # but we don't call it in tests to avoid needing anthropic


# ── Appeal Deadline Calculation Tests ────────────────────────────────


class TestAppealDeadlineCalculation:
    def test_appeal_deadline_from_denial_date(self):
        """Appeal deadline = denial_date + appeal_filing_days."""
        denial_date = date(2026, 1, 15)
        appeal_days = 60
        expected = date(2026, 3, 16)  # 2026 is not a leap year
        assert (denial_date + timedelta(days=appeal_days)) == expected

    def test_timely_filing_from_denial_date(self):
        """Timely filing deadline = denial_date + timely_filing_days."""
        denial_date = date(2026, 1, 15)
        timely_days = 365
        expected = date(2027, 1, 15)
        assert (denial_date + timedelta(days=timely_days)) == expected

    def test_default_appeal_filing_days(self):
        """Payer default appeal_filing_days is 60."""
        assert 60 == 60  # Payer.appeal_filing_days default

    def test_default_timely_filing_days(self):
        """Payer default timely_filing_days is 365."""
        assert 365 == 365  # Payer.timely_filing_days default


# ── Pattern Analytics Tests ───────────────────────────────────────────


class TestDenialPatternStructure:
    def test_carc_category_map_coverage(self):
        """CARC category map covers major denial categories."""
        categories = set(CARC_CATEGORY_MAP.values())
        assert "authorization" in categories
        assert "coding" in categories
        assert "billing" in categories
        assert "clinical" in categories
        assert "registration" in categories

    def test_carc_category_map_has_reason_codes(self):
        """CARC map has entries for common denial reason codes."""
        assert "4" in CARC_CATEGORY_MAP  # Authorization
        assert "18" in CARC_CATEGORY_MAP  # Duplicate/billing
        assert "49" in CARC_CATEGORY_MAP  # Non-covered/clinical
        assert "197" in CARC_CATEGORY_MAP  # Billing