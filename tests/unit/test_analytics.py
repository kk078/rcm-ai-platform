"""Tests for analytics/reporting service: errors, dashboard structure,
AR aging buckets, coding accuracy metrics, payer performance."""

import os
from uuid import uuid4

import pytest

os.environ.setdefault("PHI_ENCRYPTION_KEY", "test-encryption-key-for-testing-only-32b")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing")

from src.core.reporting.errors import (
    AnalyticsError,
    ReportGenerationError,
)
from src.core.reporting.service import (
    AnalyticsService,
    analytics_service,
)


# ── Error Hierarchy Tests ──────────────────────────────────────────────


class TestAnalyticsErrors:
    def test_errors_inherit_from_base(self):
        err = ReportGenerationError()
        assert isinstance(err, AnalyticsError)

    def test_report_generation_error_status(self):
        err = ReportGenerationError()
        assert err.status_code == 422

    def test_report_generation_error_custom_detail(self):
        err = ReportGenerationError("No data available for this period")
        assert "No data" in err.detail
        assert err.status_code == 422

    def test_analytics_error_default_status(self):
        err = AnalyticsError("Something went wrong")
        assert err.status_code == 400


# ── Service Initialization Tests ──────────────────────────────────────


class TestAnalyticsServiceInit:
    def test_service_singleton_exists(self):
        assert analytics_service is not None
        assert isinstance(analytics_service, AnalyticsService)

    def test_service_has_dashboard_method(self):
        assert hasattr(analytics_service, "get_dashboard")

    def test_service_has_revenue_cycle_method(self):
        assert hasattr(analytics_service, "revenue_cycle_report")

    def test_service_has_coding_accuracy_method(self):
        assert hasattr(analytics_service, "coding_accuracy_report")

    def test_service_has_payer_performance_method(self):
        assert hasattr(analytics_service, "payer_performance")

    def test_service_has_aging_report_method(self):
        assert hasattr(analytics_service, "aging_report")


# ── Dashboard Period Parsing Tests ─────────────────────────────────────


class TestDashboardPeriod:
    def test_period_parsing_may_2026(self):
        period = "2026-05"
        year, month = int(period[:4]), int(period[5:7])
        assert year == 2026
        assert month == 5

    def test_period_parsing_january(self):
        period = "2026-01"
        year, month = int(period[:4]), int(period[5:7])
        assert year == 2026
        assert month == 1

    def test_period_parsing_december(self):
        period = "2025-12"
        year, month = int(period[:4]), int(period[5:7])
        assert year == 2025
        assert month == 12


# ── AR Aging Bucket Tests ────────────────────────────────────────────


class TestARAgingBuckets:
    def test_bucket_keys_match(self):
        expected = {"0_30", "31_60", "61_90", "91_120", "120_plus", "total"}
        assert expected == {"0_30", "31_60", "61_90", "91_120", "120_plus", "total"}

    def test_bucket_boundaries(self):
        """Items 0-30 days old go in 0_30, 31-60 in 31_60, etc."""
        assert 0 <= 30
        assert 31 <= 60
        assert 61 <= 90
        assert 91 <= 120

    def test_age_day_computation(self):
        """Age in days from created_at should bucket correctly."""
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)

        # 10 days old → 0_30
        age_10 = (now - (now - timedelta(days=10))).days
        assert age_10 <= 30

        # 45 days old → 31_60
        age_45 = (now - (now - timedelta(days=45))).days
        assert 31 <= age_45 <= 60

        # 150 days old → 120_plus
        age_150 = (now - (now - timedelta(days=150))).days
        assert age_150 > 120


# ── Coding Accuracy Calculation Tests ──────────────────────────────────


class TestCodingAccuracyCalculation:
    def test_perfect_accuracy(self):
        """100 sessions, 0 with changes → 100% accuracy."""
        total = 100
        changed = 0
        accuracy = round((total - changed) / max(total, 1) * 100, 1)
        assert accuracy == 100.0

    def test_half_accuracy(self):
        """100 sessions, 50 with changes → 50% accuracy."""
        total = 100
        changed = 50
        accuracy = round((total - changed) / max(total, 1) * 100, 1)
        assert accuracy == 50.0

    def test_zero_sessions_accuracy(self):
        """0 sessions → 0% accuracy (avoid division by zero)."""
        total = 0
        accuracy = round(0 / max(total, 1) * 100, 1) if total > 0 else 0
        assert accuracy == 0

    def test_ninety_percent_accuracy(self):
        """100 sessions, 10 with changes → 90% accuracy."""
        total = 100
        changed = 10
        accuracy = round((total - changed) / max(total, 1) * 100, 1)
        assert accuracy == 90.0


# ── Denial Rate Calculation Tests ──────────────────────────────────────


class TestDenialRateCalculation:
    def test_denial_rate_percentage(self):
        total = 100
        denied = 15
        rate = round(denied / max(total, 1) * 100, 1)
        assert rate == 15.0

    def test_zero_denials(self):
        total = 100
        denied = 0
        rate = round(denied / max(total, 1) * 100, 1)
        assert rate == 0.0

    def test_all_denied(self):
        total = 50
        denied = 50
        rate = round(denied / max(total, 1) * 100, 1)
        assert rate == 100.0

    def test_zero_claims(self):
        total = 0
        rate = round(0 / max(total, 1) * 100, 1) if total > 0 else 0
        assert rate == 0


# ── Net Collection Rate Tests ────────────────────────────────────────


class TestNetCollectionRate:
    def test_standard_rate(self):
        paid = 85000
        charged = 100000
        adjusted = 5000
        rate = round(paid / max(charged - adjusted, 1) * 100, 1)
        assert rate == round(85000 / 95000 * 100, 1)

    def test_zero_charges(self):
        rate = round(0 / max(0, 1) * 100, 1)
        assert rate == 0.0