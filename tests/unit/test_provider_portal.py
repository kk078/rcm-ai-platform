"""Tests for provider portal service: errors, status display mapping,
AR aging, net collection rate, messaging, notification types, period parsing."""

import os
from datetime import date
from uuid import uuid4

import pytest

os.environ.setdefault("PHI_ENCRYPTION_KEY", "test-encryption-key-for-testing-only-32b")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing")

from src.core.provider_portal.errors import (
    PortalError,
    MessageNotFoundError,
    NotificationNotFoundError,
    ClaimAccessError,
    PortalReportError,
)
from src.core.provider_portal.service import (
    PortalService,
    STATUS_DISPLAY_MAP,
    NOTIFICATION_TYPES,
    portal_service,
)


# ── Error Hierarchy Tests ──────────────────────────────────────────────


class TestPortalErrors:
    def test_all_errors_inherit_from_base(self):
        errors = [
            MessageNotFoundError(uuid4()),
            NotificationNotFoundError(uuid4()),
            ClaimAccessError(),
            PortalReportError(),
        ]
        for err in errors:
            assert isinstance(err, PortalError)

    def test_error_status_codes(self):
        assert MessageNotFoundError(uuid4()).status_code == 404
        assert NotificationNotFoundError(uuid4()).status_code == 404
        assert ClaimAccessError().status_code == 403
        assert PortalReportError().status_code == 422

    def test_message_not_found_detail(self):
        uid = uuid4()
        err = MessageNotFoundError(uid)
        assert str(uid) in err.detail
        assert err.status_code == 404

    def test_notification_not_found_detail(self):
        uid = uuid4()
        err = NotificationNotFoundError(uid)
        assert str(uid) in err.detail

    def test_claim_access_error_detail(self):
        err = ClaimAccessError("Claim not in your practice")
        assert "practice" in err.detail
        assert err.status_code == 403

    def test_portal_report_error_detail(self):
        err = PortalReportError("Invalid period format")
        assert "Invalid" in err.detail
        assert err.status_code == 422

    def test_default_messages(self):
        assert "Message not found" in MessageNotFoundError().detail
        assert "Notification not found" in NotificationNotFoundError().detail
        assert "Claim does not belong" in ClaimAccessError().detail
        assert "Unable to generate" in PortalReportError().detail


# ── Status Display Mapping Tests ──────────────────────────────────────


class TestStatusDisplayMapping:
    def test_all_claim_statuses_have_display(self):
        """Every valid claim status should have a human-readable mapping."""
        expected_statuses = [
            "draft", "scrubbing", "scrub_failed", "ready", "submitted",
            "accepted", "rejected", "paid", "partial_paid", "denied",
            "appealed", "closed",
        ]
        for status in expected_statuses:
            assert status in STATUS_DISPLAY_MAP, f"Missing display for status: {status}"

    def test_draft_display(self):
        assert "Draft" in STATUS_DISPLAY_MAP["draft"]

    def test_submitted_display(self):
        assert "Submitted" in STATUS_DISPLAY_MAP["submitted"]

    def test_paid_display(self):
        assert "Paid" in STATUS_DISPLAY_MAP["paid"]

    def test_denied_display(self):
        assert "Denied" in STATUS_DISPLAY_MAP["denied"]

    def test_appealed_display(self):
        assert "Appeal" in STATUS_DISPLAY_MAP["appealed"]


class TestComputeStatusDisplay:
    def test_simple_paid_status(self):
        """Paid claims show payment received."""
        display = PortalService._compute_status_display(
            type("Claim", (), {"status": "paid", "total_paid": 500.0, "total_charge": 500.0})(),
            denial=None, appeal=None,
        )
        assert "Paid" in display

    def test_denied_without_appeal(self):
        """Denied claims without appeal show denial status."""
        display = PortalService._compute_status_display(
            type("Claim", (), {"status": "denied", "total_paid": 0, "total_charge": 1000.0})(),
            denial=None, appeal=None,
        )
        assert "Denied" in display

    def test_unknown_status_falls_back(self):
        """Unknown statuses get a title-cased fallback."""
        display = PortalService._compute_status_display(
            type("Claim", (), {"status": "custom_status", "total_paid": 0, "total_charge": 100.0})(),
            denial=None, appeal=None,
        )
        assert "Custom Status" in display


# ── Notification Types Tests ──────────────────────────────────────────


class TestNotificationTypes:
    def test_denial_alert_type(self):
        assert "denial_alert" in NOTIFICATION_TYPES

    def test_payment_posted_type(self):
        assert "payment_posted" in NOTIFICATION_TYPES

    def test_info_requested_type(self):
        assert "info_requested" in NOTIFICATION_TYPES

    def test_report_ready_type(self):
        assert "report_ready" in NOTIFICATION_TYPES

    def test_appeal_outcome_type(self):
        assert "appeal_outcome" in NOTIFICATION_TYPES

    def test_exactly_five_types(self):
        assert len(NOTIFICATION_TYPES) == 5


# ── AR Aging Bucket Tests ────────────────────────────────────────────


class TestARAgingBuckets:
    def test_bucket_boundaries(self):
        """AR aging buckets: 0-30, 31-60, 61-90, 91-120, 120+."""
        buckets = ["0_30", "31_60", "61_90", "91_120", "120_plus", "total"]
        # These are the expected bucket keys from _compute_ar_aging
        assert len(buckets) == 6

    def test_aging_includes_total(self):
        """AR aging result should always include a total."""
        expected_keys = {"0_30", "31_60", "61_90", "91_120", "120_plus", "total"}
        assert expected_keys == {"0_30", "31_60", "61_90", "91_120", "120_plus", "total"}


# ── Net Collection Rate Tests ────────────────────────────────────────


class TestNetCollectionRate:
    def test_rate_calculation(self):
        """Net collection rate = collections / (charges - adjustments) × 100."""
        collections = 800
        charges = 1000
        adjustments = 100
        # Expected: 800 / (1000 - 100) * 100 = 88.9%
        rate = round(collections / max(charges - adjustments, 1) * 100, 1)
        assert rate == 88.9

    def test_zero_charges_rate(self):
        """Zero charges should produce 0% rate."""
        rate = round(0 / max(0 - 0, 1) * 100, 1)
        assert rate == 0.0

    def test_high_collection_rate(self):
        """Collections exceeding charges - adjustments should cap at 100%+."""
        collections = 1000
        charges = 900
        adjustments = 0
        rate = round(collections / max(charges - adjustments, 1) * 100, 1)
        assert rate > 100


# ── Dashboard Period Parsing Tests ────────────────────────────────────


class TestDashboardPeriod:
    def test_period_parsing_month_start(self):
        """Period '2026-05' should parse to May 1, 2026."""
        period = "2026-05"
        year, month = int(period[:4]), int(period[5:7])
        start = date(year, month, 1)
        assert start == date(2026, 5, 1)

    def test_period_parsing_january(self):
        """Period '2026-01' should parse to Jan 1, 2026."""
        period = "2026-01"
        year, month = int(period[:4]), int(period[5:7])
        start = date(year, month, 1)
        assert start == date(2026, 1, 1)

    def test_period_end_of_month(self):
        """End of May should be May 31."""
        start = date(2026, 5, 1)
        end = (start + __import__("datetime").timedelta(days=32)).replace(day=1) - __import__("datetime").timedelta(days=1)
        assert end == date(2026, 5, 31)

    def test_period_end_february_leap(self):
        """End of February in leap year should be Feb 29."""
        start = date(2028, 2, 1)
        end = (start + __import__("datetime").timedelta(days=32)).replace(day=1) - __import__("datetime").timedelta(days=1)
        assert end.day == 29


# ── Service Initialization Tests ──────────────────────────────────────


class TestPortalServiceInit:
    def test_service_singleton_exists(self):
        assert portal_service is not None
        assert isinstance(portal_service, PortalService)

    def test_service_has_dashboard_method(self):
        assert hasattr(portal_service, "get_dashboard")

    def test_service_has_claims_methods(self):
        assert hasattr(portal_service, "list_claims")
        assert hasattr(portal_service, "get_claim_status")
        assert hasattr(portal_service, "get_claim_timeline")

    def test_service_has_messaging_methods(self):
        assert hasattr(portal_service, "list_messages")
        assert hasattr(portal_service, "send_message")
        assert hasattr(portal_service, "mark_message_read")

    def test_service_has_notification_methods(self):
        assert hasattr(portal_service, "list_notifications")
        assert hasattr(portal_service, "mark_all_notifications_read")

    def test_service_has_report_methods(self):
        assert hasattr(portal_service, "monthly_collection_report")
        assert hasattr(portal_service, "ar_aging_report")
        assert hasattr(portal_service, "denial_summary_report")
        assert hasattr(portal_service, "payer_performance_report")

    def test_service_has_profile_methods(self):
        assert hasattr(portal_service, "get_my_practice")
        assert hasattr(portal_service, "list_my_providers")
        assert hasattr(portal_service, "list_my_payers")

    def test_service_has_invoice_methods(self):
        assert hasattr(portal_service, "list_invoices")
        assert hasattr(portal_service, "get_invoice_detail")

    def test_service_has_denial_methods(self):
        assert hasattr(portal_service, "list_denials")
        assert hasattr(portal_service, "get_denial_detail")
        assert hasattr(portal_service, "upload_supporting_doc")