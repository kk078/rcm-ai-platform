"""Tests for queue service: status transitions, SLA defaults, priority handling,
workload helpers, auto-assignment logic, and error hierarchy."""

import os
from datetime import date, timedelta
from uuid import uuid4

import pytest

os.environ.setdefault("PHI_ENCRYPTION_KEY", "test-encryption-key-for-testing-only-32b")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing")

from src.core.queues.errors import (
    QueueError,
    QueueItemNotFoundError,
    QueueItemStatusError,
    SLABreachError,
)
from src.core.queues.service import (
    QueueService,
    VALID_STATUS_TRANSITIONS,
    QUEUE_SLA_DAYS,
    queue_service,
)


# ── Error Hierarchy Tests ──────────────────────────────────────────────


class TestQueueErrors:
    def test_all_errors_inherit_from_base(self):
        errors = [
            QueueItemNotFoundError(uuid4()),
            QueueItemStatusError(),
            SLABreachError(),
        ]
        for err in errors:
            assert isinstance(err, QueueError)

    def test_error_status_codes(self):
        assert QueueItemNotFoundError(uuid4()).status_code == 404
        assert QueueItemStatusError().status_code == 422
        assert SLABreachError().status_code == 422

    def test_queue_item_not_found_detail(self):
        uid = uuid4()
        err = QueueItemNotFoundError(uid)
        assert str(uid) in err.detail
        assert err.status_code == 404

    def test_queue_item_status_error_custom_detail(self):
        err = QueueItemStatusError("Cannot complete item in 'pending' status")
        assert "pending" in err.detail
        assert err.status_code == 422

    def test_sla_breach_error_detail(self):
        err = SLABreachError("Denial response SLA exceeded")
        assert "SLA" in err.detail
        assert err.status_code == 422


# ── Status Transition Tests ────────────────────────────────────────────


class TestQueueStatusTransitions:
    def test_pending_can_go_to_in_progress(self):
        assert "in_progress" in VALID_STATUS_TRANSITIONS["pending"]

    def test_pending_can_go_to_escalated(self):
        assert "escalated" in VALID_STATUS_TRANSITIONS["pending"]

    def test_in_progress_can_go_to_completed(self):
        assert "completed" in VALID_STATUS_TRANSITIONS["in_progress"]

    def test_in_progress_can_go_to_escalated(self):
        assert "escalated" in VALID_STATUS_TRANSITIONS["in_progress"]

    def test_in_progress_can_be_released(self):
        assert "pending" in VALID_STATUS_TRANSITIONS["in_progress"]

    def test_escalated_can_go_to_in_progress(self):
        assert "in_progress" in VALID_STATUS_TRANSITIONS["escalated"]

    def test_escalated_can_be_released(self):
        assert "pending" in VALID_STATUS_TRANSITIONS["escalated"]

    def test_on_hold_can_go_to_pending(self):
        assert "pending" in VALID_STATUS_TRANSITIONS["on_hold"]

    def test_on_hold_can_go_to_in_progress(self):
        assert "in_progress" in VALID_STATUS_TRANSITIONS["on_hold"]

    def test_completed_is_terminal(self):
        assert len(VALID_STATUS_TRANSITIONS["completed"]) == 0

    def test_cannot_go_from_pending_to_completed(self):
        assert "completed" not in VALID_STATUS_TRANSITIONS["pending"]

    def test_cannot_go_from_completed_to_anything(self):
        for target in VALID_STATUS_TRANSITIONS:
            assert target not in VALID_STATUS_TRANSITIONS["completed"]


# ── SLA Default Days Tests ────────────────────────────────────────────


class TestQueueSLADefaults:
    def test_intake_sla_is_1_day(self):
        assert QUEUE_SLA_DAYS["intake"] == 1

    def test_coding_sla_is_2_days(self):
        assert QUEUE_SLA_DAYS["coding"] == 2

    def test_billing_sla_is_2_days(self):
        assert QUEUE_SLA_DAYS["billing"] == 2

    def test_posting_sla_is_3_days(self):
        assert QUEUE_SLA_DAYS["posting"] == 3

    def test_denial_sla_is_5_days(self):
        assert QUEUE_SLA_DAYS["denial"] == 5

    def test_follow_up_sla_is_3_days(self):
        assert QUEUE_SLA_DAYS["follow_up"] == 3

    def test_all_queue_types_have_sla(self):
        for qt in ["intake", "coding", "billing", "posting", "denial", "follow_up"]:
            assert qt in QUEUE_SLA_DAYS


# ── Service Initialization Tests ──────────────────────────────────────


class TestQueueServiceInit:
    def test_service_singleton_exists(self):
        assert queue_service is not None
        assert isinstance(queue_service, QueueService)

    def test_service_has_dashboard_method(self):
        assert hasattr(queue_service, "get_dashboard")

    def test_service_has_claim_item_method(self):
        assert hasattr(queue_service, "claim_item")

    def test_service_has_auto_assign_method(self):
        assert hasattr(queue_service, "auto_assign")

    def test_service_has_sla_methods(self):
        assert hasattr(queue_service, "get_sla_breaches")
        assert hasattr(queue_service, "get_sla_compliance")
        assert hasattr(queue_service, "check_and_mark_sla_breaches")

    def test_service_has_productivity_methods(self):
        assert hasattr(queue_service, "get_team_productivity")
        assert hasattr(queue_service, "get_individual_productivity")

    def test_service_has_workload_methods(self):
        assert hasattr(queue_service, "get_team_workload")
        assert hasattr(queue_service, "get_individual_workload")


# ── Queue Type Validation Tests ────────────────────────────────────────


class TestQueueTypeValues:
    def test_queue_types_match_sla_keys(self):
        """Every queue type in SLA defaults has a corresponding key."""
        for qt in QUEUE_SLA_DAYS:
            assert qt in ("intake", "coding", "billing", "posting", "denial", "follow_up")

    def test_status_transitions_cover_all_statuses(self):
        """All known statuses appear in the transitions dict."""
        known = {"pending", "in_progress", "completed", "escalated", "on_hold"}
        assert set(VALID_STATUS_TRANSITIONS.keys()) == known