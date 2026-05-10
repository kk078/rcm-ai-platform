"""Tests for coding service: coder changes computation, code validation,
code lookup, document extraction, and error hierarchy."""

import os
import pytest

os.environ.setdefault("PHI_ENCRYPTION_KEY", "test-encryption-key-for-testing-only-32b")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing")

from src.core.coding.errors import (
    CodingError,
    CodingSessionNotFoundError,
    EncounterNotFoundError,
    CodingSessionAlreadyApprovedError,
    AIServiceUnavailableError,
    CodeValidationFailedError,
    DocumentExtractionError,
)
from src.core.coding.service import (
    CodingService,
    CodeLookupService,
    _compute_coder_changes,
    _build_suggested_codes_json,
    _detect_code_system,
    _extract_text_from_document,
)
from src.core.rules_engine.scrubber import ClaimScrubber


# ── Code System Detection Tests ─────────────────────────────────────


class TestCodeSystemDetection:
    def test_icd10_simple(self):
        assert _detect_code_system("A00") == "ICD-10-CM"

    def test_icd10_with_decimal(self):
        assert _detect_code_system("M54.5") == "ICD-10-CM"

    def test_icd10_long_decimal(self):
        assert _detect_code_system("E11.65") == "ICD-10-CM"

    def test_cpt_code(self):
        assert _detect_code_system("99213") == "CPT"

    def test_hcpcs_code(self):
        assert _detect_code_system("J0515") == "HCPCS"

    def test_unknown_format(self):
        assert _detect_code_system("ABC") == "unknown"


# ── Coder Changes Diff Tests ────────────────────────────────────────


class TestCoderChanges:
    def test_perfect_match(self):
        """All approved codes match AI suggestions."""
        suggested = {
            "diagnoses": [
                {"code": "A00.0", "description": "Cholera due to Vibrio cholerae"},
                {"code": "M54.5", "description": "Low back pain"},
            ],
            "procedures": [
                {"code": "99213", "description": "Office visit, established patient"},
            ],
        }
        changes = _compute_coder_changes(suggested, ["A00.0", "M54.5"], ["99213"])
        assert changes["diagnosis_match_pct"] == 1.0
        assert changes["procedure_match_pct"] == 1.0
        assert changes["diagnoses_added"] == []
        assert changes["diagnoses_removed"] == []
        assert changes["procedures_added"] == []
        assert changes["procedures_removed"] == []

    def test_partial_match(self):
        """Coder removes one diagnosis and adds a procedure."""
        suggested = {
            "diagnoses": [{"code": "A00.0"}, {"code": "M54.5"}],
            "procedures": [{"code": "99213"}],
        }
        changes = _compute_coder_changes(suggested, ["A00.0"], ["99213", "99214"])
        assert changes["diagnoses_added"] == []
        assert "M54.5" in changes["diagnoses_removed"]
        assert "99214" in changes["procedures_added"]
        assert changes["diagnosis_match_pct"] == 0.5  # 1 of 2 matched
        assert changes["procedure_match_pct"] == 1.0  # 1 of 1 matched

    def test_empty_suggestions(self):
        """AI returned no suggestions; coder manually adds codes."""
        suggested = {"diagnoses": [], "procedures": []}
        changes = _compute_coder_changes(suggested, ["A00.0"], ["99213"])
        assert changes["diagnoses_added"] == ["A00.0"]
        assert changes["procedures_added"] == ["99213"]
        assert changes["diagnosis_match_pct"] == 0.0  # 0 of 0 AI suggestions matched
        assert changes["procedure_match_pct"] == 0.0

    def test_coder_removes_all_ai_suggestions(self):
        """Coder overrides all AI suggestions."""
        suggested = {
            "diagnoses": [{"code": "Z00.00"}],
            "procedures": [{"code": "99213"}],
        }
        changes = _compute_coder_changes(suggested, ["A00.0", "M54.5"], ["99215"])
        assert set(changes["diagnoses_added"]) == {"A00.0", "M54.5"}
        assert changes["diagnoses_removed"] == ["Z00.00"]
        assert changes["procedures_added"] == ["99215"]
        assert changes["procedures_removed"] == ["99213"]


# ── Code Validation Tests ────────────────────────────────────────────


class TestCodeValidation:
    def test_ncci_bundling(self):
        """NCCI edit: Column 2 bundled into Column 1."""
        scrubber = ClaimScrubber(
            ncci_data={
                "99213:99214": {
                    "column1": "99213",
                    "column2": "99214",
                    "modifier_indicator": "0",
                }
            }
        )
        claim = {
            "claim_id": "test",
            "diagnoses": ["A00.0"],
            "claim_lines": [
                {"cpt_code": "99213", "modifiers": [], "units": 1},
                {"cpt_code": "99214", "modifiers": [], "units": 1},
            ],
        }
        result = scrubber.scrub(claim)
        ncci_findings = [f for f in result.findings if f.rule_type.value == "ncci_edit"]
        assert len(ncci_findings) > 0

    def test_mue_violation(self):
        """MUE: units exceed max allowed."""
        scrubber = ClaimScrubber(
            mue_data={"99213": {"max_units": 4, "rationale": "CMS"}}
        )
        claim = {
            "claim_id": "test",
            "diagnoses": ["A00.0"],
            "claim_lines": [
                {"cpt_code": "99213", "modifiers": [], "units": 10},
            ],
        }
        result = scrubber.scrub(claim)
        mue_findings = [f for f in result.findings if f.rule_type.value == "mue"]
        assert len(mue_findings) > 0

    def test_modifier_conflict(self):
        """Modifier 26 and TC cannot appear together."""
        scrubber = ClaimScrubber()
        claim = {
            "claim_id": "test",
            "diagnoses": ["A00.0"],
            "claim_lines": [
                {"cpt_code": "71045", "modifiers": ["26", "TC"], "units": 1},
            ],
        }
        result = scrubber.scrub(claim)
        mod_findings = [f for f in result.findings if f.rule_type.value == "modifier"]
        assert len(mod_findings) > 0

    def test_validate_code_combination_method(self):
        """CodingService.validate_code_combination returns valid result for clean codes."""
        service = CodingService()
        result = service.validate_code_combination(
            diagnosis_codes=["A00.0", "M54.5"],
            procedure_codes=["99213"],
        )
        assert "valid" in result
        assert "score" in result
        assert "findings" in result
        assert isinstance(result["findings"], list)

    def test_validate_with_ncci_edit(self):
        """Validation catches bundling error."""
        service = CodingService()
        # Override scrubber with NCCI data for testing
        service.scrubber = ClaimScrubber(
            ncci_data={"99213:99214": {"column1": "99213", "column2": "99214", "modifier_indicator": "0"}}
        )
        result = service.validate_code_combination(
            diagnosis_codes=["A00.0"],
            procedure_codes=["99213", "99214"],
        )
        ncci_findings = [f for f in result["findings"] if f["rule_type"] == "ncci_edit"]
        assert len(ncci_findings) > 0


# ── Document Extraction Tests ────────────────────────────────────────


class TestDocumentExtraction:
    def test_txt_extraction(self):
        """Plain text extraction works."""
        content = b"Patient presents with chest pain."
        text = _extract_text_from_document(content, "clinical_notes.txt")
        assert "chest pain" in text

    def test_md_extraction(self):
        """Markdown extraction works."""
        content = b"# Clinical Notes\nPatient has diabetes."
        text = _extract_text_from_document(content, "notes.md")
        assert "diabetes" in text

    def test_unsupported_format(self):
        """PDF and other formats raise DocumentExtractionError."""
        with pytest.raises(DocumentExtractionError):
            _extract_text_from_document(b"fake pdf content", "report.pdf")

    def test_docx_unsupported(self):
        """DOCX format is not yet supported."""
        with pytest.raises(DocumentExtractionError):
            _extract_text_from_document(b"fake docx", "notes.docx")


# ── Error Hierarchy Tests ────────────────────────────────────────────


class TestCodingErrors:
    def test_all_errors_inherit_from_base(self):
        errors = [
            CodingSessionNotFoundError(uuid4()),
            EncounterNotFoundError(uuid4()),
            CodingSessionAlreadyApprovedError(),
            AIServiceUnavailableError(),
            CodeValidationFailedError(),
            DocumentExtractionError(),
        ]
        for err in errors:
            assert isinstance(err, CodingError)

    def test_error_status_codes(self):
        from uuid import uuid4
        assert CodingSessionNotFoundError(uuid4()).status_code == 404
        assert EncounterNotFoundError(uuid4()).status_code == 404
        assert CodingSessionAlreadyApprovedError().status_code == 409
        assert AIServiceUnavailableError().status_code == 503
        assert CodeValidationFailedError().status_code == 422
        assert DocumentExtractionError().status_code == 422

    def test_session_not_found_detail(self):
        from uuid import uuid4
        uid = uuid4()
        err = CodingSessionNotFoundError(uid)
        assert str(uid) in err.detail
        assert err.status_code == 404

    def test_encounter_not_found_detail(self):
        from uuid import uuid4
        uid = uuid4()
        err = EncounterNotFoundError(uid)
        assert str(uid) in err.detail

    def test_already_approved_detail(self):
        from uuid import uuid4
        uid = uuid4()
        err = CodingSessionAlreadyApprovedError(uid)
        assert str(uid) in err.detail
        assert err.status_code == 409

    def test_ai_unavailable_detail(self):
        err = AIServiceUnavailableError("Claude API timeout")
        assert "timeout" in err.detail
        assert err.status_code == 503

    def test_validation_failed_with_errors(self):
        err = CodeValidationFailedError("NCCI bundling error", errors={"line": 2, "code": "99214"})
        assert err.errors == {"line": 2, "code": "99214"}
        assert err.status_code == 422

    def test_document_extraction_detail(self):
        err = DocumentExtractionError("Unsupported format: .pdf")
        assert "Unsupported" in err.detail
        assert err.status_code == 422


# ── Suggested Codes JSON Builder Tests ──────────────────────────────


class TestBuildSuggestedCodesJson:
    def test_build_with_findings(self):
        """Build suggested_codes JSONB with scrub findings — using dicts to avoid anthropic import."""
        from src.core.rules_engine.scrubber import ScrubFinding, RuleType, RuleSeverity

        # Build a mock AICodingResponse-like object using simple namespace
        from types import SimpleNamespace
        ai_response = SimpleNamespace(
            diagnoses=[
                SimpleNamespace(code="A00.0", code_system="ICD-10-CM", description="Cholera",
                                confidence=0.95, rationale="Patient symptoms match",
                                supporting_text="Fever and dehydration", guideline_reference=None),
            ],
            procedures=[
                SimpleNamespace(code="99213", code_system="CPT", description="Office visit",
                                confidence=0.9, rationale="Standard follow-up",
                                supporting_text="Office visit note", guideline_reference=None),
            ],
            entities_extracted={"conditions": ["cholera"], "medications": []},
            reasoning="Patient presents with classic cholera symptoms",
        )
        findings = [
            ScrubFinding(
                rule_type=RuleType.NCCI_EDIT,
                severity=RuleSeverity.ERROR,
                message="NCCI bundling: 99214 is bundled into 99213",
                suggestion="Add modifier 59 if services were distinct",
            )
        ]

        result = _build_suggested_codes_json(ai_response, findings)
        assert len(result["diagnoses"]) == 1
        assert result["diagnoses"][0]["code"] == "A00.0"
        assert len(result["procedures"]) == 1
        assert result["procedures"][0]["code"] == "99213"
        assert len(result["scrub_findings"]) == 1
        assert result["scrub_findings"][0]["severity"] == "error"
        assert "entities_extracted" in result


# ── Schema Validation Tests ─────────────────────────────────────────


class TestCodingSchemas:
    def test_code_system_enum(self):
        from src.api.routes.coding import CodeSystem
        assert CodeSystem.ICD10CM.value == "ICD-10-CM"
        assert CodeSystem.CPT.value == "CPT"
        assert CodeSystem.HCPCS.value == "HCPCS"

    def test_code_approval_schema(self):
        from src.api.routes.coding import CodeApproval
        approval = CodeApproval(
            approved_diagnoses=["A00.0", "M54.5"],
            approved_procedures=["99213"],
            coder_notes="Changed diagnosis per clinical notes",
        )
        assert len(approval.approved_diagnoses) == 2
        assert approval.coder_notes is not None

    def test_start_session_request_schema(self):
        from src.api.routes.coding import StartSessionRequest
        from uuid import uuid4
        req = StartSessionRequest(encounter_id=uuid4())
        assert req.encounter_id is not None

    def test_validation_result_schema(self):
        from src.api.routes.coding import ValidationResult
        result = ValidationResult(valid=True, score=100, findings=[])
        assert result.valid is True
        assert result.score == 100

    def test_approval_result_schema(self):
        from src.api.routes.coding import ApprovalResult
        from uuid import uuid4
        result = ApprovalResult(
            session_id=uuid4(),
            encounter_id=uuid4(),
            claim_id=uuid4(),
            claim_number="CLM-ABC123",
        )
        assert result.claim_number == "CLM-ABC123"


# Needed for uuid4 in test_coding_errors
from uuid import uuid4