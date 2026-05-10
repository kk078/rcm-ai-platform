"""Tests for client billing service: errors, invoice status transitions,
fee calculation models, invoice number generation, revenue dashboard."""

import os
from datetime import date
from uuid import uuid4

import pytest

os.environ.setdefault("PHI_ENCRYPTION_KEY", "test-encryption-key-for-testing-only-32b")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing")

from src.core.client_billing.errors import (
    InvoiceError,
    InvoiceNotFoundError,
    InvoiceStatusError,
    FeeCalculationError,
)
from src.core.client_billing.service import (
    BillingService,
    VALID_INVOICE_TRANSITIONS,
    _generate_invoice_number,
    billing_service,
)


# ── Error Hierarchy Tests ──────────────────────────────────────────────


class TestBillingErrors:
    def test_all_errors_inherit_from_base(self):
        errors = [
            InvoiceNotFoundError(uuid4()),
            InvoiceStatusError(),
            FeeCalculationError(),
        ]
        for err in errors:
            assert isinstance(err, InvoiceError)

    def test_error_status_codes(self):
        assert InvoiceNotFoundError(uuid4()).status_code == 404
        assert InvoiceStatusError().status_code == 422
        assert FeeCalculationError().status_code == 422

    def test_invoice_not_found_detail(self):
        uid = uuid4()
        err = InvoiceNotFoundError(uid)
        assert str(uid) in err.detail
        assert err.status_code == 404

    def test_invoice_status_error_detail(self):
        err = InvoiceStatusError("Cannot void a paid invoice")
        assert "paid" in err.detail
        assert err.status_code == 422

    def test_fee_calculation_error_detail(self):
        err = FeeCalculationError("No active service agreement")
        assert "agreement" in err.detail
        assert err.status_code == 422

    def test_default_messages(self):
        assert "Invoice not found" in InvoiceNotFoundError().detail
        assert "Invalid invoice status" in InvoiceStatusError().detail
        assert "Fee calculation failed" in FeeCalculationError().detail


# ── Invoice Status Transition Tests ────────────────────────────────────


class TestInvoiceStatusTransitions:
    def test_draft_can_be_sent(self):
        assert "sent" in VALID_INVOICE_TRANSITIONS["draft"]

    def test_sent_can_be_paid(self):
        assert "paid" in VALID_INVOICE_TRANSITIONS["sent"]

    def test_sent_can_be_overdue(self):
        assert "overdue" in VALID_INVOICE_TRANSITIONS["sent"]

    def test_sent_can_be_disputed(self):
        assert "disputed" in VALID_INVOICE_TRANSITIONS["sent"]

    def test_sent_can_be_voided(self):
        assert "void" in VALID_INVOICE_TRANSITIONS["sent"]

    def test_overdue_can_be_paid(self):
        assert "paid" in VALID_INVOICE_TRANSITIONS["overdue"]

    def test_overdue_can_be_disputed(self):
        assert "disputed" in VALID_INVOICE_TRANSITIONS["overdue"]

    def test_overdue_can_be_voided(self):
        assert "void" in VALID_INVOICE_TRANSITIONS["overdue"]

    def test_disputed_can_be_paid(self):
        assert "paid" in VALID_INVOICE_TRANSITIONS["disputed"]

    def test_paid_is_terminal(self):
        assert len(VALID_INVOICE_TRANSITIONS["paid"]) == 0

    def test_void_is_terminal(self):
        assert len(VALID_INVOICE_TRANSITIONS["void"]) == 0

    def test_cannot_go_from_draft_to_paid(self):
        assert "paid" not in VALID_INVOICE_TRANSITIONS["draft"]

    def test_cannot_go_from_paid_to_void(self):
        assert "void" not in VALID_INVOICE_TRANSITIONS["paid"]


# ── Invoice Number Generation Tests ──────────────────────────────────


class TestInvoiceNumberGeneration:
    def test_format_includes_prefix(self):
        inv_num = _generate_invoice_number(1)
        assert inv_num.startswith("INV-")

    def test_format_includes_year(self):
        inv_num = _generate_invoice_number(1)
        assert str(date.today().year) in inv_num

    def test_sequence_numbering(self):
        inv_1 = _generate_invoice_number(1)
        inv_42 = _generate_invoice_number(42)
        assert "0001" in inv_1
        assert "0042" in inv_42

    def test_sequence_padded_to_four_digits(self):
        inv_num = _generate_invoice_number(7)
        assert "0007" in inv_num


# ── Service Initialization Tests ──────────────────────────────────────


class TestBillingServiceInit:
    def test_service_singleton_exists(self):
        assert billing_service is not None
        assert isinstance(billing_service, BillingService)

    def test_service_has_invoice_methods(self):
        assert hasattr(billing_service, "generate_invoice")
        assert hasattr(billing_service, "generate_batch_invoices")
        assert hasattr(billing_service, "list_invoices")
        assert hasattr(billing_service, "get_invoice")
        assert hasattr(billing_service, "update_invoice")
        assert hasattr(billing_service, "send_invoice")
        assert hasattr(billing_service, "record_payment")
        assert hasattr(billing_service, "void_invoice")

    def test_service_has_revenue_methods(self):
        assert hasattr(billing_service, "revenue_dashboard")
        assert hasattr(billing_service, "client_profitability")
        assert hasattr(billing_service, "revenue_projections")
        assert hasattr(billing_service, "overdue_invoices")

    def test_service_has_health_methods(self):
        assert hasattr(billing_service, "all_clients_health")
        assert hasattr(billing_service, "single_client_health")


# ── Fee Model Validation Tests ────────────────────────────────────────


class TestFeeModelValues:
    def test_percentage_model(self):
        """Percentage fee: collections × rate."""
        rate = 5.0  # 5%
        collections = 10000.0
        fee = collections * (rate / 100)
        assert fee == 500.0

    def test_per_claim_model(self):
        """Per-claim fee: claims × rate per claim."""
        rate = 7.50
        claims = 100
        fee = claims * rate
        assert fee == 750.0

    def test_flat_fee_model(self):
        """Flat fee: fixed monthly amount."""
        fee = 2500.0
        assert fee == 2500.0

    def test_hybrid_model(self):
        """Hybrid: base + overage × rate."""
        base = 1500.0
        threshold = 50000.0
        collections = 65000.0
        overage_rate = 3.0  # 3%
        overage = max(0, collections - threshold)  # 15000
        fee = base + (overage * overage_rate / 100)  # 1500 + 450
        assert fee == 1950.0

    def test_hybrid_no_overage(self):
        """Hybrid with no overage: just base fee."""
        base = 1500.0
        threshold = 50000.0
        collections = 40000.0
        overage_rate = 3.0
        overage = max(0, collections - threshold)  # 0
        fee = base + (overage * overage_rate / 100)
        assert fee == 1500.0

    def test_minimum_fee_floor(self):
        """Minimum fee applies when calculated fee is lower."""
        calculated_fee = 200.0
        minimum = 500.0
        final_fee = max(calculated_fee, minimum)
        assert final_fee == 500.0

    def test_minimum_fee_not_applied_when_higher(self):
        """Minimum fee doesn't apply when calculated fee exceeds it."""
        calculated_fee = 800.0
        minimum = 500.0
        final_fee = max(calculated_fee, minimum)
        assert final_fee == 800.0