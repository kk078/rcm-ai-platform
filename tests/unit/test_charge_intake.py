"""Tests for charge intake: ChargeEntryService, BatchImportService, validation, errors."""

import os
from datetime import date
from uuid import uuid4

import pytest

os.environ.setdefault("PHI_ENCRYPTION_KEY", "test-encryption-key-for-testing-only-32b")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing")

from src.core.charge_intake.errors import (
    ChargeIntakeError,
    ChargeNotFoundError,
    ChargeValidationError,
    DuplicateChargeError,
    InvalidCSVFormatError,
)
from src.core.charge_intake.service import (
    ChargeEntryService,
    BatchImportService,
    validate_diagnosis_codes,
    validate_cpt_code,
    ICD10_PATTERN,
    CPT_PATTERN,
)


# ── Validation Tests ────────────────────────────────────────────────────


class TestICD10Validation:
    """Test ICD-10 code format validation."""

    def test_valid_icd10_simple(self):
        """Simple ICD-10: letter + 2 digits."""
        errors = validate_diagnosis_codes(["A00"])
        assert len(errors) == 0

    def test_valid_icd10_with_decimal(self):
        """ICD-10 with decimal: letter + 2 digits + . + 1-4 digits."""
        errors = validate_diagnosis_codes(["A00.1"])
        assert len(errors) == 0

    def test_valid_icd10_long_decimal(self):
        """ICD-10 with long decimal suffix."""
        errors = validate_diagnosis_codes(["M54.5123"])
        assert len(errors) == 0

    def test_invalid_icd10_no_letter(self):
        """ICD-10 must start with a letter."""
        errors = validate_diagnosis_codes(["123.4"])
        assert len(errors) == 1
        assert "Invalid ICD-10" in errors[0]

    def test_invalid_icd10_too_short(self):
        """ICD-10 must have at least 3 characters."""
        errors = validate_diagnosis_codes(["A1"])
        assert len(errors) == 1

    def test_invalid_icd10_wrong_decimal_format(self):
        """ICD-10 decimal part must be 1-4 digits."""
        errors = validate_diagnosis_codes(["A00.12345"])
        assert len(errors) == 1

    def test_empty_diagnosis_codes_pass(self):
        """Empty list of diagnosis codes is valid (not required at submit)."""
        errors = validate_diagnosis_codes([])
        assert len(errors) == 0


class TestCPTValidation:
    """Test CPT code format validation."""

    def test_valid_cpt(self):
        """CPT code must be exactly 5 digits."""
        errors = validate_cpt_code("99213")
        assert len(errors) == 0

    def test_invalid_cpt_too_short(self):
        errors = validate_cpt_code("9921")
        assert len(errors) == 1
        assert "Invalid CPT" in errors[0]

    def test_invalid_cpt_too_long(self):
        errors = validate_cpt_code("992131")
        assert len(errors) == 1

    def test_invalid_cpt_letters(self):
        errors = validate_cpt_code("A9213")
        assert len(errors) == 1


class TestICD10Pattern:
    """Direct regex pattern tests for ICD-10."""

    def test_pattern_matches(self):
        assert ICD10_PATTERN.match("A00")
        assert ICD10_PATTERN.match("Z98.8")
        assert ICD10_PATTERN.match("M54.5123")

    def test_pattern_rejects(self):
        assert not ICD10_PATTERN.match("00A")
        assert not ICD10_PATTERN.match("A")
        assert not ICD10_PATTERN.match("A0")
        assert not ICD10_PATTERN.match("A00.")


class TestCPTPattern:
    """Direct regex pattern tests for CPT."""

    def test_pattern_matches(self):
        assert CPT_PATTERN.match("99213")
        assert CPT_PATTERN.match("10000")

    def test_pattern_rejects(self):
        assert not CPT_PATTERN.match("9921")
        assert not CPT_PATTERN.match("992131")
        assert not CPT_PATTERN.match("A9213")


# ── Error Hierarchy Tests ──────────────────────────────────────────────


class TestChargeIntakeErrors:
    """Test the charge intake error hierarchy."""

    def test_all_errors_inherit_from_base(self):
        errors = [
            ChargeNotFoundError(uuid4()),
            ChargeValidationError(),
            DuplicateChargeError(),
            InvalidCSVFormatError(),
        ]
        for err in errors:
            assert isinstance(err, ChargeIntakeError)

    def test_error_status_codes(self):
        assert ChargeNotFoundError(uuid4()).status_code == 404
        assert ChargeValidationError().status_code == 422
        assert DuplicateChargeError().status_code == 409
        assert InvalidCSVFormatError().status_code == 422

    def test_charge_not_found_detail(self):
        uid = uuid4()
        err = ChargeNotFoundError(uid)
        assert str(uid) in err.detail
        assert err.status_code == 404

    def test_charge_validation_error_with_details(self):
        err = ChargeValidationError("Missing patient", errors={"patient": "required"})
        assert err.detail == "Missing patient"
        assert err.errors == {"patient": "required"}
        assert err.status_code == 422

    def test_duplicate_charge_detail(self):
        err = DuplicateChargeError("Same patient + DOS + CPT")
        assert "Same patient" in err.detail
        assert err.status_code == 409

    def test_invalid_csv_format_detail(self):
        err = InvalidCSVFormatError("Missing column: patient_name")
        assert "Missing column" in err.detail
        assert err.status_code == 422


# ── ChargeEntryService Tests ─────────────────────────────────────────────


class TestChargeEntryService:
    """Test ChargeEntryService methods that don't require DB."""

    def test_validate_charge_data_missing_patient(self):
        """Charge must have either patient_id or patient_name."""
        from src.api.routes.charge_intake import ChargeEntryCreate
        # No patient_id or patient_name — validation should catch it
        data = ChargeEntryCreate(
            service_date=date(2026, 1, 15),
            rendering_provider_id=uuid4(),
        )
        service = ChargeEntryService()
        errors = service._validate_charge_data(data)
        assert any("patient" in e.lower() for e in errors)

    def test_validate_charge_data_future_date(self):
        """Service date in the future should fail validation."""
        from src.api.routes.charge_intake import ChargeEntryCreate
        data = ChargeEntryCreate(
            patient_id=uuid4(),
            service_date=date(2099, 1, 1),
            rendering_provider_id=uuid4(),
        )
        service = ChargeEntryService()
        errors = service._validate_charge_data(data)
        assert any("future" in e.lower() for e in errors)

    def test_validate_charge_data_valid(self):
        """Valid charge data should produce no errors."""
        from src.api.routes.charge_intake import ChargeEntryCreate, ProcedureEntry
        data = ChargeEntryCreate(
            patient_id=uuid4(),
            service_date=date(2026, 1, 15),
            rendering_provider_id=uuid4(),
            diagnosis_codes=["A00.1", "M54.5"],
            procedures=[
                ProcedureEntry(cpt_code="99213", charge_amount=150.0),
            ],
        )
        service = ChargeEntryService()
        errors = service._validate_charge_data(data)
        assert len(errors) == 0

    def test_validate_charge_data_invalid_icd10(self):
        """Invalid ICD-10 code should produce an error."""
        from src.api.routes.charge_intake import ChargeEntryCreate
        data = ChargeEntryCreate(
            patient_id=uuid4(),
            service_date=date(2026, 1, 15),
            rendering_provider_id=uuid4(),
            diagnosis_codes=["INVALID"],
        )
        service = ChargeEntryService()
        errors = service._validate_charge_data(data)
        assert any("ICD-10" in e for e in errors)

    def test_validate_charge_data_invalid_cpt_in_diagnosis(self):
        """Invalid ICD-10 in diagnosis_codes is caught by service validation."""
        from src.api.routes.charge_intake import ChargeEntryCreate
        data = ChargeEntryCreate(
            patient_id=uuid4(),
            service_date=date(2026, 1, 15),
            rendering_provider_id=uuid4(),
            diagnosis_codes=["NOTACODE"],
        )
        service = ChargeEntryService()
        errors = service._validate_charge_data(data)
        assert any("ICD-10" in e for e in errors)

    def test_validate_charge_data_needs_coding_flag(self):
        """needs_coding=True is valid even without procedures."""
        from src.api.routes.charge_intake import ChargeEntryCreate
        data = ChargeEntryCreate(
            patient_name="John Doe",
            service_date=date(2026, 1, 15),
            rendering_provider_id=uuid4(),
            needs_coding=True,
        )
        service = ChargeEntryService()
        # needs_coding doesn't auto-fail validation, but no procedures is fine
        errors = service._validate_charge_data(data)
        # Should not error on missing patient_id since patient_name is provided
        assert not any("patient" in e.lower() and "required" in e.lower() for e in errors)


# ── BatchImportService Tests ─────────────────────────────────────────────


class TestBatchImportService:
    """Test BatchImportService CSV parsing and validation."""

    def test_parse_date_yyyy_mm_dd(self):
        result = BatchImportService._parse_date("2026-01-15")
        assert result == date(2026, 1, 15)

    def test_parse_date_mm_dd_yyyy(self):
        result = BatchImportService._parse_date("01/15/2026")
        assert result == date(2026, 1, 15)

    def test_parse_date_empty(self):
        result = BatchImportService._parse_date("")
        assert result is None

    def test_parse_date_invalid(self):
        result = BatchImportService._parse_date("not-a-date")
        assert result is None

    def test_validate_csv_row_missing_required_field(self):
        row = {"patient_name": "", "service_date": "2026-01-15", "cpt": "99213"}
        errors = BatchImportService._validate_csv_row(row, 2)
        assert any(e["field"] == "patient_name" for e in errors)

    def test_validate_csv_row_missing_cpt(self):
        row = {"patient_name": "John Doe", "service_date": "2026-01-15", "cpt": ""}
        errors = BatchImportService._validate_csv_row(row, 2)
        assert any(e["field"] == "cpt" for e in errors)

    def test_validate_csv_row_invalid_cpt(self):
        row = {"patient_name": "John Doe", "service_date": "2026-01-15", "cpt": "123"}
        errors = BatchImportService._validate_csv_row(row, 2)
        assert any(e["field"] == "cpt" for e in errors)

    def test_validate_csv_row_invalid_icd10(self):
        row = {
            "patient_name": "John Doe",
            "service_date": "2026-01-15",
            "cpt": "99213",
            "dx1": "INVALID",
        }
        errors = BatchImportService._validate_csv_row(row, 2)
        assert any("ICD-10" in e["message"] for e in errors)

    def test_validate_csv_row_valid(self):
        row = {
            "patient_name": "John Doe",
            "service_date": "2026-01-15",
            "cpt": "99213",
            "dx1": "A00.1",
        }
        errors = BatchImportService._validate_csv_row(row, 2)
        assert len(errors) == 0


# ── Schema Validation Tests ─────────────────────────────────────────────


class TestChargeSchemas:
    """Test Pydantic schema validation."""

    def test_charge_entry_create_minimal(self):
        from src.api.routes.charge_intake import ChargeEntryCreate
        data = ChargeEntryCreate(
            service_date=date(2026, 1, 15),
            rendering_provider_id=uuid4(),
        )
        assert data.place_of_service == "11"
        assert data.needs_coding is False
        assert data.diagnosis_codes == []

    def test_charge_entry_create_with_procedures(self):
        from src.api.routes.charge_intake import ChargeEntryCreate, ProcedureEntry
        proc = ProcedureEntry(cpt_code="99213", modifiers=["25"], units=1, charge_amount=150.0)
        data = ChargeEntryCreate(
            patient_id=uuid4(),
            service_date=date(2026, 1, 15),
            rendering_provider_id=uuid4(),
            procedures=[proc],
            diagnosis_codes=["A00.1"],
        )
        assert len(data.procedures) == 1
        assert data.procedures[0].cpt_code == "99213"
        assert data.diagnosis_codes == ["A00.1"]

    def test_procedure_entry_invalid_cpt(self):
        from src.api.routes.charge_intake import ProcedureEntry
        with pytest.raises(Exception):
            ProcedureEntry(cpt_code="abcde", charge_amount=100.0)

    def test_missing_info_request_schema(self):
        from src.api.routes.charge_intake import MissingInfoRequest
        req = MissingInfoRequest(
            message="Need diagnosis codes",
            fields_needed=["diagnosis_codes", "authorization_number"],
            urgent=True,
        )
        assert req.urgent is True
        assert len(req.fields_needed) == 2

    def test_reject_request_schema(self):
        from src.api.routes.charge_intake import RejectRequest
        req = RejectRequest(reason="Duplicate charge")
        assert req.reason == "Duplicate charge"

    def test_charge_status_enum(self):
        from src.api.routes.charge_intake import ChargeStatus
        assert ChargeStatus.RECEIVED.value == "received"
        assert ChargeStatus.NEEDS_CODING.value == "needs_coding"
        assert ChargeStatus.READY_TO_BILL.value == "ready_to_bill"

    def test_validation_result_schema(self):
        from src.api.routes.charge_intake import ValidationResult
        result = ValidationResult(valid=True, errors=[])
        assert result.valid is True
        assert len(result.errors) == 0

    def test_routing_result_schema(self):
        from src.api.routes.charge_intake import RoutingResult
        result = RoutingResult(charge_id=uuid4())
        assert result.encounter_id is None
        assert result.claim_id is None