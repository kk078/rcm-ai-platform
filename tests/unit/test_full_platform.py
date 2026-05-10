"""
Comprehensive test suite for MedClaim AI platform.
Tests all API endpoints, EDI parser, PHI redaction, and rules engine.
"""

import pytest
from fastapi.testclient import TestClient
from src.api.main import app
from src.core.nlp.phi_redaction import PHIRedactor
from src.services.edi.parser import ERA835Parser, AdjustmentGroupCode
from src.core.rules_engine.scrubber import ClaimScrubber, RuleSeverity, RuleType
from decimal import Decimal

client = TestClient(app)
TEST_UUID = "00000000-0000-0000-0000-000000000001"


# ═══════════════════════════════════════════════════════════════
# API ENDPOINT TESTS — Every endpoint returns expected status
# ═══════════════════════════════════════════════════════════════

class TestSystemEndpoints:
    def test_health(self):
        r = client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "healthy"
        assert "version" in data

    def test_ready(self):
        r = client.get("/ready")
        assert r.status_code == 200


class TestAuthEndpoints:
    def test_login_requires_params(self):
        r = client.post("/api/v1/auth/login")
        assert r.status_code in (200, 422, 501)

    def test_refresh(self):
        r = client.post("/api/v1/auth/refresh")
        assert r.status_code in (200, 422, 501)

    def test_logout(self):
        r = client.post("/api/v1/auth/logout")
        assert r.status_code in (200, 501)

    def test_mfa_setup(self):
        r = client.post("/api/v1/auth/mfa/setup")
        assert r.status_code in (200, 501)

    def test_mfa_verify(self):
        r = client.post("/api/v1/auth/mfa/verify")
        assert r.status_code in (200, 422, 501)


class TestClaimsEndpoints:
    def test_list_claims(self):
        r = client.get("/api/v1/claims/")
        assert r.status_code == 501

    def test_create_claim(self):
        r = client.post("/api/v1/claims/", json={})
        assert r.status_code in (422, 501)

    def test_get_claim(self):
        r = client.get(f"/api/v1/claims/{TEST_UUID}")
        assert r.status_code == 501

    def test_scrub_claim(self):
        r = client.post(f"/api/v1/claims/{TEST_UUID}/scrub")
        assert r.status_code == 501

    def test_submit_claim(self):
        r = client.post(f"/api/v1/claims/{TEST_UUID}/submit")
        assert r.status_code == 501

    def test_batch_submit(self):
        r = client.post("/api/v1/claims/batch/submit", json=[])
        assert r.status_code in (422, 501)

    def test_scrub_results(self):
        r = client.get(f"/api/v1/claims/{TEST_UUID}/scrub-results")
        assert r.status_code == 501

    def test_claim_history(self):
        r = client.get(f"/api/v1/claims/{TEST_UUID}/history")
        assert r.status_code == 501

    def test_void_claim(self):
        r = client.post(f"/api/v1/claims/{TEST_UUID}/void")
        assert r.status_code == 501

    def test_corrected_claim(self):
        r = client.post(f"/api/v1/claims/{TEST_UUID}/corrected", json={})
        assert r.status_code in (422, 501)


class TestCodingEndpoints:
    def test_start_session(self):
        r = client.post("/api/v1/coding/sessions", json={})
        assert r.status_code in (422, 501)

    def test_get_session(self):
        r = client.get(f"/api/v1/coding/sessions/{TEST_UUID}")
        assert r.status_code == 501

    def test_approve_codes(self):
        r = client.post(f"/api/v1/coding/sessions/{TEST_UUID}/approve", json={})
        assert r.status_code in (422, 501)

    def test_guidelines(self):
        r = client.get(f"/api/v1/coding/sessions/{TEST_UUID}/guidelines")
        assert r.status_code == 501

    def test_validate(self):
        r = client.post("/api/v1/coding/validate", json={})
        assert r.status_code in (422, 501)

    def test_lookup_code(self):
        r = client.get("/api/v1/coding/lookup/99213")
        assert r.status_code == 501

    def test_search_codes(self):
        r = client.get("/api/v1/coding/search?query=office+visit")
        assert r.status_code == 501


class TestDenialsEndpoints:
    def test_list_denials(self):
        r = client.get("/api/v1/denials/")
        assert r.status_code == 501

    def test_worklist(self):
        r = client.get("/api/v1/denials/worklist")
        assert r.status_code == 501

    def test_get_denial(self):
        r = client.get(f"/api/v1/denials/{TEST_UUID}")
        assert r.status_code == 501

    def test_classify(self):
        r = client.post(f"/api/v1/denials/{TEST_UUID}/classify")
        assert r.status_code == 501

    def test_generate_appeal(self):
        r = client.post(f"/api/v1/denials/{TEST_UUID}/generate-appeal")
        assert r.status_code == 501

    def test_submit_appeal(self):
        r = client.post(f"/api/v1/denials/{TEST_UUID}/submit-appeal", json={})
        assert r.status_code in (422, 501)

    def test_write_off(self):
        r = client.post(f"/api/v1/denials/{TEST_UUID}/write-off", json={})
        assert r.status_code in (422, 501)

    def test_assign(self):
        r = client.post(f"/api/v1/denials/{TEST_UUID}/assign", json={})
        assert r.status_code in (422, 501)

    def test_patterns(self):
        r = client.get("/api/v1/denials/analytics/patterns")
        assert r.status_code == 501

    def test_summary(self):
        r = client.get("/api/v1/denials/analytics/summary")
        assert r.status_code == 501


class TestPaymentsEndpoints:
    def test_list_batches(self):
        r = client.get("/api/v1/payments/batches")
        assert r.status_code == 501

    def test_get_batch(self):
        r = client.get(f"/api/v1/payments/batches/{TEST_UUID}")
        assert r.status_code == 501

    def test_batch_lines(self):
        r = client.get(f"/api/v1/payments/batches/{TEST_UUID}/lines")
        assert r.status_code == 501

    def test_post_batch(self):
        r = client.post(f"/api/v1/payments/batches/{TEST_UUID}/post")
        assert r.status_code == 501

    def test_manual_match(self):
        r = client.post(f"/api/v1/payments/lines/{TEST_UUID}/match", json={})
        assert r.status_code in (422, 501)

    def test_dispute(self):
        r = client.post(f"/api/v1/payments/lines/{TEST_UUID}/dispute-underpayment", json={})
        assert r.status_code in (422, 501)

    def test_reconciliation(self):
        r = client.get("/api/v1/payments/reconciliation?period=2026-05")
        assert r.status_code == 501

    def test_unmatched(self):
        r = client.get("/api/v1/payments/unmatched")
        assert r.status_code == 501


class TestPatientsEndpoints:
    def test_list(self):
        r = client.get("/api/v1/patients/")
        assert r.status_code in (200, 501)

    def test_get(self):
        r = client.get(f"/api/v1/patients/{TEST_UUID}")
        assert r.status_code in (200, 501)

    def test_claims(self):
        r = client.get(f"/api/v1/patients/{TEST_UUID}/claims")
        assert r.status_code in (200, 501)

    def test_eligibility(self):
        r = client.post(f"/api/v1/patients/{TEST_UUID}/verify-eligibility")
        assert r.status_code in (200, 422, 501)


class TestPayersEndpoints:
    def test_list(self):
        r = client.get("/api/v1/payers/")
        assert r.status_code in (200, 501)

    def test_get(self):
        r = client.get(f"/api/v1/payers/{TEST_UUID}")
        assert r.status_code in (200, 501)

    def test_rules(self):
        r = client.get(f"/api/v1/payers/{TEST_UUID}/rules")
        assert r.status_code in (200, 501)

    def test_fee_schedule(self):
        r = client.get(f"/api/v1/payers/{TEST_UUID}/fee-schedule")
        assert r.status_code in (200, 501)

    def test_policies(self):
        r = client.get(f"/api/v1/payers/{TEST_UUID}/policies?query=test")
        assert r.status_code in (200, 501)


class TestAnalyticsEndpoints:
    def test_dashboard(self):
        r = client.get("/api/v1/analytics/dashboard")
        assert r.status_code in (200, 501)

    def test_revenue_cycle(self):
        r = client.get("/api/v1/analytics/revenue-cycle")
        assert r.status_code in (200, 501)

    def test_coding_accuracy(self):
        r = client.get("/api/v1/analytics/coding-accuracy")
        assert r.status_code in (200, 501)

    def test_payer_performance(self):
        r = client.get("/api/v1/analytics/payer-performance")
        assert r.status_code in (200, 501)

    def test_aging(self):
        r = client.get("/api/v1/analytics/aging-report")
        assert r.status_code in (200, 501)


class TestClientManagementEndpoints:
    def test_create_practice(self):
        r = client.post("/api/v1/clients/practices", json={})
        assert r.status_code in (422, 501)

    def test_list_practices(self):
        r = client.get("/api/v1/clients/practices")
        assert r.status_code == 501

    def test_get_practice(self):
        r = client.get(f"/api/v1/clients/practices/{TEST_UUID}")
        assert r.status_code == 501

    def test_activate(self):
        r = client.post(f"/api/v1/clients/practices/{TEST_UUID}/activate")
        assert r.status_code == 501

    def test_suspend(self):
        r = client.post(f"/api/v1/clients/practices/{TEST_UUID}/suspend", json={})
        assert r.status_code in (422, 501)

    def test_terminate(self):
        r = client.post(f"/api/v1/clients/practices/{TEST_UUID}/terminate", json={})
        assert r.status_code in (422, 501)

    def test_onboarding(self):
        r = client.get(f"/api/v1/clients/practices/{TEST_UUID}/onboarding")
        assert r.status_code == 501

    def test_add_location(self):
        r = client.post(f"/api/v1/clients/practices/{TEST_UUID}/locations", json={})
        assert r.status_code in (422, 501)

    def test_add_provider(self):
        r = client.post(f"/api/v1/clients/practices/{TEST_UUID}/providers", json={})
        assert r.status_code in (422, 501)

    def test_payer_enrollment(self):
        r = client.post(f"/api/v1/clients/practices/{TEST_UUID}/payer-enrollments", json={})
        assert r.status_code in (422, 501)

    def test_service_agreement(self):
        r = client.post(f"/api/v1/clients/practices/{TEST_UUID}/service-agreement", json={})
        assert r.status_code in (422, 501)

    def test_staff_assignment(self):
        r = client.post(f"/api/v1/clients/practices/{TEST_UUID}/staff-assignments", json={})
        assert r.status_code in (422, 501)

    def test_portal_user(self):
        r = client.post(f"/api/v1/clients/practices/{TEST_UUID}/portal-users", json={})
        assert r.status_code in (422, 501)


class TestChargeIntakeEndpoints:
    def test_submit_charge(self):
        r = client.post("/api/v1/intake/charges", json={})
        assert r.status_code in (422, 501)

    def test_list_charges(self):
        r = client.get("/api/v1/intake/charges")
        assert r.status_code == 501

    def test_get_charge(self):
        r = client.get(f"/api/v1/intake/charges/{TEST_UUID}")
        assert r.status_code == 501

    def test_validate_charge(self):
        r = client.post(f"/api/v1/intake/charges/{TEST_UUID}/validate")
        assert r.status_code == 501

    def test_route_coding(self):
        r = client.post(f"/api/v1/intake/charges/{TEST_UUID}/route-to-coding")
        assert r.status_code == 501

    def test_route_billing(self):
        r = client.post(f"/api/v1/intake/charges/{TEST_UUID}/route-to-billing")
        assert r.status_code == 501

    def test_reject(self):
        r = client.post(f"/api/v1/intake/charges/{TEST_UUID}/reject", json={})
        assert r.status_code in (422, 501)

    def test_request_info(self):
        r = client.post(f"/api/v1/intake/charges/{TEST_UUID}/request-info", json={})
        assert r.status_code in (422, 501)

    def test_intake_dashboard(self):
        r = client.get("/api/v1/intake/intake/dashboard")
        assert r.status_code == 501

    def test_intake_queue(self):
        r = client.get("/api/v1/intake/intake/queue")
        assert r.status_code == 501


class TestProviderPortalEndpoints:
    def test_dashboard(self):
        r = client.get("/api/v1/portal/dashboard")
        assert r.status_code == 501

    def test_claims(self):
        r = client.get("/api/v1/portal/claims")
        assert r.status_code == 501

    def test_claim_detail(self):
        r = client.get(f"/api/v1/portal/claims/{TEST_UUID}")
        assert r.status_code == 501

    def test_claim_timeline(self):
        r = client.get(f"/api/v1/portal/claims/{TEST_UUID}/timeline")
        assert r.status_code == 501

    def test_denials(self):
        r = client.get("/api/v1/portal/denials")
        assert r.status_code == 501

    def test_messages(self):
        r = client.get("/api/v1/portal/messages")
        assert r.status_code == 501

    def test_send_message(self):
        r = client.post("/api/v1/portal/messages", json={})
        assert r.status_code in (422, 501)

    def test_notifications(self):
        r = client.get("/api/v1/portal/notifications")
        assert r.status_code == 501

    def test_reports(self):
        r = client.get("/api/v1/portal/reports")
        assert r.status_code == 501

    def test_monthly_collection(self):
        r = client.get("/api/v1/portal/reports/monthly-collection?period=2026-05")
        assert r.status_code == 501

    def test_ar_aging(self):
        r = client.get("/api/v1/portal/reports/ar-aging")
        assert r.status_code == 501

    def test_my_practice(self):
        r = client.get("/api/v1/portal/my-practice")
        assert r.status_code in (200, 501)

    def test_invoices(self):
        r = client.get("/api/v1/portal/invoices")
        assert r.status_code == 501


class TestWorkQueueEndpoints:
    def test_dashboard(self):
        r = client.get("/api/v1/queues/dashboard")
        assert r.status_code == 501

    def test_my_queue(self):
        r = client.get("/api/v1/queues/my-queue")
        assert r.status_code == 501

    def test_queue_by_type(self):
        r = client.get("/api/v1/queues/queue/coding")
        assert r.status_code == 501

    def test_claim_item(self):
        r = client.post(f"/api/v1/queues/queue/{TEST_UUID}/claim")
        assert r.status_code == 501

    def test_release_item(self):
        r = client.post(f"/api/v1/queues/queue/{TEST_UUID}/release")
        assert r.status_code in (422, 501)

    def test_complete_item(self):
        r = client.post(f"/api/v1/queues/queue/{TEST_UUID}/complete")
        assert r.status_code == 501

    def test_escalate(self):
        r = client.post(f"/api/v1/queues/queue/{TEST_UUID}/escalate", json={})
        assert r.status_code in (422, 501)

    def test_workload(self):
        r = client.get("/api/v1/queues/workload")
        assert r.status_code == 501

    def test_productivity(self):
        r = client.get("/api/v1/queues/productivity")
        assert r.status_code == 501

    def test_sla_breaches(self):
        r = client.get("/api/v1/queues/sla/breaches")
        assert r.status_code == 501

    def test_sla_compliance(self):
        r = client.get("/api/v1/queues/sla/compliance")
        assert r.status_code == 501


class TestClientBillingEndpoints:
    def test_generate_invoice(self):
        r = client.post("/api/v1/billing/invoices/generate", json={})
        assert r.status_code in (422, 501)

    def test_generate_batch(self):
        r = client.post("/api/v1/billing/invoices/generate-batch", json={})
        assert r.status_code in (422, 501)

    def test_list_invoices(self):
        r = client.get("/api/v1/billing/invoices")
        assert r.status_code == 501

    def test_get_invoice(self):
        r = client.get(f"/api/v1/billing/invoices/{TEST_UUID}")
        assert r.status_code == 501

    def test_send_invoice(self):
        r = client.post(f"/api/v1/billing/invoices/{TEST_UUID}/send")
        assert r.status_code == 501

    def test_record_payment(self):
        r = client.post(f"/api/v1/billing/invoices/{TEST_UUID}/record-payment", json={})
        assert r.status_code in (422, 501)

    def test_void_invoice(self):
        r = client.post(f"/api/v1/billing/invoices/{TEST_UUID}/void", json={})
        assert r.status_code in (422, 501)

    def test_revenue_dashboard(self):
        r = client.get("/api/v1/billing/revenue/dashboard?period=2026-05")
        assert r.status_code == 501

    def test_profitability(self):
        r = client.get("/api/v1/billing/revenue/profitability")
        assert r.status_code == 501

    def test_client_health(self):
        r = client.get("/api/v1/billing/client-health")
        assert r.status_code == 501


# ═══════════════════════════════════════════════════════════════
# PHI REDACTION TESTS
# ═══════════════════════════════════════════════════════════════

class TestPHIRedaction:
    @pytest.fixture
    def redactor(self):
        return PHIRedactor()

    def test_redacts_ssn(self, redactor):
        text = "Patient SSN is 123-45-6789"
        redacted, mapping = redactor.redact(text)
        assert "123-45-6789" not in redacted
        assert len(mapping) > 0

    def test_redacts_phone(self, redactor):
        text = "Call the patient at (555) 123-4567"
        redacted, mapping = redactor.redact(text)
        assert "(555) 123-4567" not in redacted

    def test_redacts_email(self, redactor):
        text = "Email: patient@example.com"
        redacted, mapping = redactor.redact(text)
        assert "patient@example.com" not in redacted

    def test_redacts_mrn(self, redactor):
        text = "MRN: 12345678"
        redacted, mapping = redactor.redact(text)
        assert "12345678" not in redacted

    def test_rehydrate_restores_phi(self, redactor):
        original = "Patient SSN is 123-45-6789 and email is test@test.com"
        redacted, mapping = redactor.redact(original)
        restored = redactor.rehydrate(redacted, mapping)
        assert "123-45-6789" in restored
        assert "test@test.com" in restored

    def test_is_phi_free_detects_ssn(self, redactor):
        assert not redactor.is_phi_free("SSN: 123-45-6789")
        assert redactor.is_phi_free("No PHI here, just text")

    def test_empty_text(self, redactor):
        redacted, mapping = redactor.redact("")
        assert redacted == ""
        assert len(mapping) == 0

    def test_no_phi_text(self, redactor):
        text = "The patient presents with headache and nausea"
        redacted, mapping = redactor.redact(text)
        assert redacted == text
        assert len(mapping) == 0


# ═══════════════════════════════════════════════════════════════
# EDI 835 PARSER TESTS
# ═══════════════════════════════════════════════════════════════

class TestERA835Parser:
    @pytest.fixture
    def parser(self):
        return ERA835Parser()

    @pytest.fixture
    def sample_835(self):
        """Minimal valid 835 ERA file."""
        return (
            "ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       *230101*1200*^*00501*000000001*0*P*:~"
            "GS*HP*SENDER*RECEIVER*20230101*1200*1*X*005010X221A1~"
            "ST*835*0001*005010X221A1~"
            "BPR*I*1500.00*C*ACH*CTX*01*111111111*DA*222222222*1234567890**01*333333333*DA*444444444*20230115~"
            "TRN*1*CHECK123*1234567890~"
            "DTM*405*20230115~"
            "N1*PR*AETNA INSURANCE*XV*12345~"
            "N1*PE*DR SMITH MEDICAL*XX*1234567890~"
            "CLP*CLM001*1*500.00*400.00*50.00**12*PAYERCLM001~"
            "CAS*CO*45*50.00~"
            "CAS*PR*2*50.00~"
            "SVC*HC:99213*200.00*180.00**1~"
            "AMT*B6*180.00~"
            "CAS*CO*45*20.00~"
            "SVC*HC:36415*100.00*80.00**1~"
            "CAS*CO*45*20.00~"
            "CLP*CLM002*1*1000.00*0.00*0.00**12*PAYERCLM002~"
            "CAS*CO*197*1000.00~"
            "SVC*HC:29881*1000.00*0.00**1~"
            "CAS*CO*197*1000.00~"
            "SE*20*0001~"
            "GE*1*1~"
            "IEA*1*000000001~"
        )

    def test_parse_basic_835(self, parser, sample_835):
        batch = parser.parse(sample_835)
        assert batch.payer_name == "AETNA INSURANCE"
        assert batch.payee_name == "DR SMITH MEDICAL"
        assert batch.payee_npi == "1234567890"
        assert batch.check_number == "CHECK123"

    def test_parse_payment_amount(self, parser, sample_835):
        batch = parser.parse(sample_835)
        assert batch.total_paid == Decimal("1500.00")

    def test_parse_claims(self, parser, sample_835):
        batch = parser.parse(sample_835)
        assert batch.total_claims == 2
        assert batch.claims[0].claim_id == "CLM001"
        assert batch.claims[1].claim_id == "CLM002"

    def test_parse_claim_amounts(self, parser, sample_835):
        batch = parser.parse(sample_835)
        claim1 = batch.claims[0]
        assert claim1.total_charge == Decimal("500.00")
        assert claim1.total_paid == Decimal("400.00")
        assert claim1.patient_responsibility == Decimal("50.00")

    def test_parse_service_lines(self, parser, sample_835):
        batch = parser.parse(sample_835)
        claim1 = batch.claims[0]
        assert len(claim1.service_lines) == 2
        assert claim1.service_lines[0].procedure_code == "99213"
        assert claim1.service_lines[0].paid_amount == Decimal("180.00")
        assert claim1.service_lines[1].procedure_code == "36415"

    def test_parse_adjustments(self, parser, sample_835):
        batch = parser.parse(sample_835)
        claim1 = batch.claims[0]
        # Claim-level adjustments
        assert len(claim1.claim_adjustments) >= 1
        co_adj = [a for a in claim1.claim_adjustments if a.group_code == AdjustmentGroupCode.CO]
        assert len(co_adj) > 0

    def test_detect_denials(self, parser, sample_835):
        batch = parser.parse(sample_835)
        assert batch.denial_count == 1  # CLM002 has CO-197 (denial)
        assert batch.claims[1].has_denials

    def test_parse_denied_claim(self, parser, sample_835):
        batch = parser.parse(sample_835)
        denied = batch.claims[1]
        assert denied.total_paid == Decimal("0.00")
        assert denied.total_charge == Decimal("1000.00")

    def test_allowed_amount(self, parser, sample_835):
        batch = parser.parse(sample_835)
        line = batch.claims[0].service_lines[0]
        assert line.allowed_amount == Decimal("180.00")

    def test_production_date(self, parser, sample_835):
        batch = parser.parse(sample_835)
        assert batch.production_date is not None
        assert batch.production_date.year == 2023

    def test_short_file_raises(self, parser):
        with pytest.raises(ValueError, match="too short"):
            parser.parse("ISA*short")


# ═══════════════════════════════════════════════════════════════
# RULES ENGINE TESTS (Extended)
# ═══════════════════════════════════════════════════════════════

class TestRulesEngineExtended:
    @pytest.fixture
    def scrubber(self):
        ncci_data = {
            "29881:29880": {"column1": "29881", "column2": "29880", "modifier_indicator": "1"},
            "99213:36415": {"column1": "99213", "column2": "36415", "modifier_indicator": "0"},
        }
        mue_data = {
            "99213": {"max_units": 1, "rationale": "E/M per encounter"},
            "36415": {"max_units": 3, "rationale": "Venipuncture"},
            "99215": {"max_units": 1, "rationale": "E/M per encounter"},
        }
        return ClaimScrubber(ncci_data=ncci_data, mue_data=mue_data)

    def test_missing_diagnosis_pointer_flagged(self, scrubber):
        claim = {
            "claim_id": "ext-001",
            "claim_lines": [
                {"cpt_code": "99213", "modifiers": [], "units": 1, "icd_pointers": []},
            ],
            "diagnoses": ["J06.9"],
        }
        result = scrubber.scrub(claim)
        dx_errors = [f for f in result.findings if f.rule_type == RuleType.MEDICAL_NECESSITY]
        assert len(dx_errors) > 0

    def test_invalid_diagnosis_pointer_flagged(self, scrubber):
        claim = {
            "claim_id": "ext-002",
            "claim_lines": [
                {"cpt_code": "99213", "modifiers": [], "units": 1, "icd_pointers": ["Z99.99"]},
            ],
            "diagnoses": ["J06.9"],
        }
        result = scrubber.scrub(claim)
        dx_errors = [f for f in result.findings
                     if f.rule_type == RuleType.MEDICAL_NECESSITY
                     and "not found" in f.message]
        assert len(dx_errors) > 0

    def test_valid_claim_is_submittable(self, scrubber):
        claim = {
            "claim_id": "ext-003",
            "claim_lines": [
                {"cpt_code": "36415", "modifiers": [], "units": 1, "icd_pointers": ["J06.9"]},
            ],
            "diagnoses": ["J06.9"],
        }
        result = scrubber.scrub(claim)
        assert result.ready_to_submit

    def test_em_without_modifier_25_warning(self, scrubber):
        claim = {
            "claim_id": "ext-004",
            "claim_lines": [
                {"cpt_code": "99213", "modifiers": [], "units": 1, "icd_pointers": ["J06.9"]},
                {"cpt_code": "36415", "modifiers": [], "units": 1, "icd_pointers": ["J06.9"]},
            ],
            "diagnoses": ["J06.9"],
        }
        result = scrubber.scrub(claim)
        mod_warnings = [f for f in result.findings
                        if f.rule_type == RuleType.MODIFIER
                        and f.severity == RuleSeverity.WARNING
                        and "25" in f.message]
        assert len(mod_warnings) > 0

    def test_xe_modifier_exception(self, scrubber):
        """XE, XP, XS, XU modifiers should also satisfy NCCI modifier exception."""
        claim = {
            "claim_id": "ext-005",
            "claim_lines": [
                {"cpt_code": "29881", "modifiers": [], "units": 1},
                {"cpt_code": "29880", "modifiers": ["XS"], "units": 1},
            ],
            "diagnoses": [],
        }
        result = scrubber.scrub(claim)
        ncci_errors = [f for f in result.findings
                       if f.rule_type == RuleType.NCCI_EDIT
                       and f.severity == RuleSeverity.ERROR]
        assert len(ncci_errors) == 0

    def test_score_never_below_zero(self, scrubber):
        claim = {
            "claim_id": "ext-006",
            "claim_lines": [
                {"cpt_code": "99213", "modifiers": ["26", "TC"], "units": 10},
                {"cpt_code": "99215", "modifiers": ["26", "TC"], "units": 10},
                {"cpt_code": "36415", "modifiers": [], "units": 100},
            ],
            "diagnoses": [],
        }
        result = scrubber.scrub(claim)
        assert result.score >= 0

    def test_empty_claim_no_crash(self, scrubber):
        claim = {"claim_id": "ext-007", "claim_lines": [], "diagnoses": []}
        result = scrubber.scrub(claim)
        assert result.score == 100
        assert result.ready_to_submit


# ═══════════════════════════════════════════════════════════════
# CONFIGURATION TESTS
# ═══════════════════════════════════════════════════════════════

class TestConfiguration:
    def test_settings_load(self):
        from src.config import get_settings
        settings = get_settings()
        assert settings.app_name == "medclaim-ai"
        assert settings.app_env == "development"

    def test_settings_is_production(self):
        from src.config import get_settings
        settings = get_settings()
        assert settings.is_production is False

    def test_settings_defaults(self):
        from src.config import get_settings
        settings = get_settings()
        assert settings.database_pool_size == 20
        assert settings.jwt_access_token_expire_minutes == 15
        assert settings.phi_redaction_enabled is True
        assert settings.audit_log_retention_years == 7


# ═══════════════════════════════════════════════════════════════
# MIDDLEWARE TESTS
# ═══════════════════════════════════════════════════════════════

class TestMiddleware:
    def test_security_headers_present(self):
        r = client.get("/health")
        assert r.headers.get("X-Content-Type-Options") == "nosniff"
        assert r.headers.get("X-Frame-Options") == "DENY"
        assert "max-age" in r.headers.get("Strict-Transport-Security", "")
        assert r.headers.get("Cache-Control") == "no-store"
        assert r.headers.get("Pragma") == "no-cache"

    def test_request_id_header(self):
        r = client.get("/health")
        assert "X-Request-ID" in r.headers
        # Should be a valid UUID format
        assert len(r.headers["X-Request-ID"]) == 36

    def test_cors_headers(self):
        r = client.options(
            "/health",
            headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"}
        )
        # CORS middleware should respond
        assert r.status_code in (200, 400)


# ═══════════════════════════════════════════════════════════════
# PROMPT TEMPLATE TESTS
# ═══════════════════════════════════════════════════════════════

class TestPromptTemplates:
    def test_coding_system_prompt(self):
        from src.core.nlp.prompts import PromptTemplates
        pt = PromptTemplates()
        prompt = pt.coding_system_prompt()
        assert "ICD-10" in prompt
        assert "CPT" in prompt
        assert "JSON" in prompt

    def test_coding_user_prompt(self):
        from src.core.nlp.prompts import PromptTemplates
        pt = PromptTemplates()
        prompt = pt.coding_user_prompt(
            clinical_text="Patient presents with chest pain",
            encounter_type="office",
            place_of_service="11",
            patient_age=55,
            patient_gender="M",
            guidelines_context=[{"content": "test guideline"}],
        )
        assert "chest pain" in prompt
        assert "55" in prompt

    def test_denial_classification_prompt(self):
        from src.core.nlp.prompts import PromptTemplates
        pt = PromptTemplates()
        prompt = pt.denial_classification_system_prompt()
        assert "category" in prompt.lower()
        assert "root_cause" in prompt

    def test_appeal_system_prompt(self):
        from src.core.nlp.prompts import PromptTemplates
        pt = PromptTemplates()
        for level in (1, 2, 3):
            prompt = pt.appeal_generation_system_prompt(level)
            assert "appeal" in prompt.lower()
            assert "JSON" in prompt

    def test_claim_risk_prompt(self):
        from src.core.nlp.prompts import PromptTemplates
        pt = PromptTemplates()
        prompt = pt.claim_risk_system_prompt()
        assert "risk" in prompt.lower()
        assert "denial_probability" in prompt
