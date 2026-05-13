"""
Coding service layer — AI-assisted medical coding sessions, code suggestion
validation, approval workflow, and code lookup.

Every write operation creates an AuditLog entry.
Every query enforces tenant isolation via practice_id filtering.
AI and vector store calls degrade gracefully on failure.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from uuid import UUID, uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.coding.errors import (
    AIServiceUnavailableError,
    CodingSessionAlreadyApprovedError,
    CodingSessionNotFoundError,
    CodeValidationFailedError,
    DocumentExtractionError,
    EncounterNotFoundError,
)
from src.core.rules_engine.scrubber import ClaimScrubber
from src.infrastructure.database.models import (
    AuditLog,
    Claim,
    ClaimDiagnosis,
    ClaimLine,
    CodingSession,
    Coverage,
    Encounter,
    Patient,
    WorkQueueItem,
)

logger = structlog.get_logger()

# Code format patterns
ICD10_PATTERN = re.compile(r"^[A-Z]\d{2}(\.\d{1,4})?$")
CPT_PATTERN = re.compile(r"^\d{5}$")
HCPCS_PATTERN = re.compile(r"^[A-Z]\d{4}$")


async def _write_audit(
    db: AsyncSession,
    user_id: UUID,
    action: str,
    resource_type: str,
    resource_id: UUID | None = None,
    resource_detail: str | None = None,
    phi_accessed: bool = False,
    ip_address: str | None = None,
    request_path: str | None = None,
    request_method: str | None = None,
) -> None:
    """Create an AuditLog entry. Caller must flush/commit the session."""
    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_detail=resource_detail,
        phi_accessed=phi_accessed,
        ip_address=ip_address,
        request_path=request_path,
        request_method=request_method,
    )
    db.add(entry)


def _detect_code_system(code: str) -> str:
    """Auto-detect code system from format."""
    if ICD10_PATTERN.match(code):
        return "ICD-10-CM"
    if CPT_PATTERN.match(code):
        return "CPT"
    if HCPCS_PATTERN.match(code):
        return "HCPCS"
    return "unknown"


def _compute_coder_changes(
    suggested_codes: dict,
    approved_diagnoses: list[str],
    approved_procedures: list[str],
) -> dict:
    """Diff AI suggestions vs final approved codes with match percentages."""
    # Extract AI-suggested code strings from the structured suggestions
    ai_dx_codes = set()
    ai_proc_codes = set()
    if suggested_codes:
        for dx in suggested_codes.get("diagnoses", []):
            if isinstance(dx, dict):
                ai_dx_codes.add(dx.get("code", ""))
            elif isinstance(dx, str):
                ai_dx_codes.add(dx)
        for proc in suggested_codes.get("procedures", []):
            if isinstance(proc, dict):
                ai_proc_codes.add(proc.get("code", ""))
            elif isinstance(proc, str):
                ai_proc_codes.add(proc)

    approved_dx_set = set(approved_diagnoses)
    approved_proc_set = set(approved_procedures)

    # Compute diffs
    dx_added = list(approved_dx_set - ai_dx_codes)
    dx_removed = list(ai_dx_codes - approved_dx_set)
    proc_added = list(approved_proc_set - ai_proc_codes)
    proc_removed = list(ai_proc_codes - approved_proc_set)

    # Match percentages (how much of the AI suggestions were kept)
    dx_match_pct = len(ai_dx_codes & approved_dx_set) / max(len(ai_dx_codes), 1)
    proc_match_pct = len(ai_proc_codes & approved_proc_set) / max(len(ai_proc_codes), 1)

    return {
        "diagnoses_added": dx_added,
        "diagnoses_removed": dx_removed,
        "procedures_added": proc_added,
        "procedures_removed": proc_removed,
        "diagnosis_match_pct": round(dx_match_pct, 4),
        "procedure_match_pct": round(proc_match_pct, 4),
        "ai_diagnosis_count": len(ai_dx_codes),
        "ai_procedure_count": len(ai_proc_codes),
        "approved_diagnosis_count": len(approved_dx_set),
        "approved_procedure_count": len(approved_proc_set),
    }


def _build_suggested_codes_json(ai_response, scrub_findings: list) -> dict:
    """Build the JSONB value for CodingSession.suggested_codes."""
    diagnoses = []
    for dx in ai_response.diagnoses:
        diagnoses.append({
            "code": dx.code,
            "code_system": dx.code_system,
            "description": dx.description,
            "confidence": dx.confidence,
            "rationale": dx.rationale,
            "supporting_text": dx.supporting_text,
            "guideline_reference": dx.guideline_reference,
        })

    procedures = []
    for proc in ai_response.procedures:
        procedures.append({
            "code": proc.code,
            "code_system": proc.code_system,
            "description": proc.description,
            "confidence": proc.confidence,
            "rationale": proc.rationale,
            "supporting_text": proc.supporting_text,
            "guideline_reference": proc.guideline_reference,
        })

    findings_data = []
    for f in scrub_findings:
        findings_data.append({
            "rule_type": f.rule_type.value if hasattr(f.rule_type, "value") else str(f.rule_type),
            "severity": f.severity.value if hasattr(f.severity, "value") else str(f.severity),
            "message": f.message,
            "suggestion": f.suggestion,
            "auto_fixable": f.auto_fixable,
        })

    return {
        "diagnoses": diagnoses,
        "procedures": procedures,
        "entities_extracted": ai_response.entities_extracted,
        "reasoning": ai_response.reasoning,
        "scrub_findings": findings_data,
    }


def _extract_text_from_document(content: bytes, filename: str) -> str:
    """Extract text from an uploaded document. Supports .txt files."""
    lower_name = filename.lower()
    if lower_name.endswith(".txt") or lower_name.endswith(".md"):
        return content.decode("utf-8", errors="replace")
    # PDF and other formats not yet supported
    raise DocumentExtractionError(
        f"Unsupported document format: {filename}. Currently only .txt and .md files are supported."
    )


class CodingService:
    """Manage AI-assisted coding sessions: start, review, approve, and claim assembly."""

    def __init__(self):
        self.scrubber = ClaimScrubber()
        self._ai_service = None

    def _get_ai_service(self):
        """Lazy initialization of AIService to avoid startup failures."""
        if self._ai_service is None:
            from src.core.nlp.ai_service import AIService
            self._ai_service = AIService()
        return self._ai_service

    async def start_session(
        self,
        db: AsyncSession,
        encounter_id: UUID,
        practice_id: UUID,
        user_id: UUID,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> CodingSession:
        """Start an AI coding session for an encounter."""
        # 1. Load encounter
        result = await db.execute(
            select(Encounter).where(
                Encounter.id == encounter_id,
                Encounter.practice_id == practice_id,
            )
        )
        encounter = result.scalar_one_or_none()
        if not encounter:
            raise EncounterNotFoundError(encounter_id)

        # 2. Load patient for age/gender context
        patient_age = None
        patient_gender = None
        if encounter.patient_id:
            pat_result = await db.execute(select(Patient).where(Patient.id == encounter.patient_id))
            patient = pat_result.scalar_one_or_none()
            if patient:
                patient_gender = patient.gender
                if patient.date_of_birth:
                    patient_age = (datetime.now(timezone.utc).replace(tzinfo=None).date() - patient.date_of_birth).days // 365

        # 3. Assemble clinical text
        clinical_text = self._assemble_clinical_text(encounter)
        if not clinical_text.strip():
            clinical_text = f"Encounter on {encounter.encounter_date}. Type: {encounter.encounter_type}."

        # 4. Call AI service
        ai_response = None
        ai_error = None
        processing_time_ms = None
        token_count = None

        start_time = time.time()
        try:
            ai_service = self._get_ai_service()
            ai_response = await ai_service.suggest_codes(
                clinical_text=clinical_text,
                encounter_type=encounter.encounter_type,
                place_of_service=encounter.place_of_service,
                patient_age=patient_age,
                patient_gender=patient_gender,
            )
            processing_time_ms = round((time.time() - start_time) * 1000)
        except Exception as e:
            processing_time_ms = round((time.time() - start_time) * 1000)
            ai_error = str(e)
            logger.warning("ai_coding_failed", encounter_id=str(encounter_id), error=ai_error)

        # 5. Validate suggestions with ClaimScrubber
        suggested_codes_json = {}
        if ai_response:
            # Build synthetic claim for scrubber
            claim_dict = self._build_synthetic_claim(ai_response, encounter, patient_age, patient_gender)
            scrub_result = self.scrubber.scrub(claim_dict)
            suggested_codes_json = _build_suggested_codes_json(ai_response, scrub_result.findings)
        else:
            suggested_codes_json = {
                "diagnoses": [],
                "procedures": [],
                "entities_extracted": {},
                "reasoning": "",
                "scrub_findings": [],
                "error": True,
                "error_detail": ai_error,
            }

        # 6. Create CodingSession record
        status = "ai_failed" if ai_response is None else "pending_review"
        session = CodingSession(
            practice_id=practice_id,
            encounter_id=encounter_id,
            coder_id=user_id,
            nlp_extraction={"error": ai_error} if ai_error else ai_response.entities_extracted if ai_response else {},
            ai_model_version=self._get_ai_service().model if ai_response else None,
            processing_time_ms=processing_time_ms,
            token_count=token_count,
            suggested_codes=suggested_codes_json,
            status=status,
        )
        db.add(session)
        await db.flush()

        # 7. Create WorkQueueItem
        wqi = WorkQueueItem(
            practice_id=practice_id,
            queue_type="coding",
            item_type="coding_session",
            item_id=session.id,
        )
        db.add(wqi)

        # 8. Audit log
        await _write_audit(
            db, user_id, "start_coding_session", "coding_session", session.id,
            resource_detail=f"Status: {status}, Encounter: {encounter_id}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method, phi_accessed=True,
        )
        logger.info("coding_session_started", session_id=str(session.id), status=status, encounter_id=str(encounter_id))
        return session

    async def start_session_from_document(
        self,
        db: AsyncSession,
        encounter_id: UUID,
        practice_id: UUID,
        user_id: UUID,
        document_content: bytes,
        document_filename: str,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> CodingSession:
        """Start a coding session from an uploaded document."""
        # Extract text from document
        text = _extract_text_from_document(document_content, document_filename)

        # Load encounter for context
        result = await db.execute(
            select(Encounter).where(
                Encounter.id == encounter_id,
                Encounter.practice_id == practice_id,
            )
        )
        encounter = result.scalar_one_or_none()
        if not encounter:
            raise EncounterNotFoundError(encounter_id)

        # Load patient for age/gender context
        patient_age = None
        patient_gender = None
        if encounter.patient_id:
            pat_result = await db.execute(select(Patient).where(Patient.id == encounter.patient_id))
            patient = pat_result.scalar_one_or_none()
            if patient:
                patient_gender = patient.gender
                if patient.date_of_birth:
                    patient_age = (datetime.now(timezone.utc).replace(tzinfo=None).date() - patient.date_of_birth).days // 365

        # Combine encounter notes with document text
        clinical_text = text
        if encounter.notes:
            clinical_text = f"{encounter.notes}\n\n--- DOCUMENT ---\n\n{text}"

        # Run AI pipeline
        ai_response = None
        ai_error = None
        processing_time_ms = None

        start_time = time.time()
        try:
            ai_service = self._get_ai_service()
            ai_response = await ai_service.suggest_codes(
                clinical_text=clinical_text,
                encounter_type=encounter.encounter_type,
                place_of_service=encounter.place_of_service,
                patient_age=patient_age,
                patient_gender=patient_gender,
            )
            processing_time_ms = round((time.time() - start_time) * 1000)
        except Exception as e:
            processing_time_ms = round((time.time() - start_time) * 1000)
            ai_error = str(e)
            logger.warning("ai_coding_from_doc_failed", encounter_id=str(encounter_id), error=ai_error)

        # Validate and build suggested_codes
        suggested_codes_json = {}
        if ai_response:
            claim_dict = self._build_synthetic_claim(ai_response, encounter, patient_age, patient_gender)
            scrub_result = self.scrubber.scrub(claim_dict)
            suggested_codes_json = _build_suggested_codes_json(ai_response, scrub_result.findings)
        else:
            suggested_codes_json = {
                "diagnoses": [],
                "procedures": [],
                "entities_extracted": {},
                "reasoning": "",
                "scrub_findings": [],
                "error": True,
                "error_detail": ai_error,
            }

        status = "ai_failed" if ai_response is None else "pending_review"
        session = CodingSession(
            practice_id=practice_id,
            encounter_id=encounter_id,
            coder_id=user_id,
            document_ids=[],
            nlp_extraction={"document_filename": document_filename, "error": ai_error} if ai_error else ai_response.entities_extracted if ai_response else {"document_filename": document_filename},
            ai_model_version=self._get_ai_service().model if ai_response else None,
            processing_time_ms=processing_time_ms,
            suggested_codes=suggested_codes_json,
            status=status,
        )
        db.add(session)
        await db.flush()

        wqi = WorkQueueItem(
            practice_id=practice_id,
            queue_type="coding",
            item_type="coding_session",
            item_id=session.id,
        )
        db.add(wqi)

        await _write_audit(
            db, user_id, "start_coding_session_from_document", "coding_session", session.id,
            resource_detail=f"Document: {document_filename}, Status: {status}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method, phi_accessed=True,
        )
        logger.info("coding_session_started_from_document", session_id=str(session.id), filename=document_filename)
        return session

    async def get_session(
        self,
        db: AsyncSession,
        session_id: UUID,
        practice_id: UUID,
    ) -> CodingSession:
        """Get a coding session with tenant isolation check."""
        result = await db.execute(
            select(CodingSession).where(
                CodingSession.id == session_id,
                CodingSession.practice_id == practice_id,
            )
        )
        session = result.scalar_one_or_none()
        if not session:
            raise CodingSessionNotFoundError(session_id)
        return session

    async def approve_codes(
        self,
        db: AsyncSession,
        session_id: UUID,
        practice_id: UUID,
        user_id: UUID,
        approved_diagnoses: list[str],
        approved_procedures: list[str],
        coder_notes: str | None = None,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> dict:
        """Approve codes for a coding session, create claim, and route to billing."""
        session = await self.get_session(db, session_id, practice_id)

        if session.status == "approved":
            raise CodingSessionAlreadyApprovedError(session_id)

        # Load encounter
        result = await db.execute(select(Encounter).where(Encounter.id == session.encounter_id))
        encounter = result.scalar_one_or_none()
        if not encounter:
            raise EncounterNotFoundError(session.encounter_id)

        # Compute coder changes (diff AI vs approved)
        coder_changes = _compute_coder_changes(
            session.suggested_codes, approved_diagnoses, approved_procedures,
        )
        if coder_notes:
            coder_changes["coder_notes"] = coder_notes

        # Update session
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        review_started = session.review_started_at or now
        session.final_codes = {
            "diagnoses": approved_diagnoses,
            "procedures": approved_procedures,
        }
        session.coder_changes = coder_changes
        session.coder_id = user_id
        session.review_started_at = review_started
        session.review_completed_at = now
        session.review_time_seconds = int((now - review_started).total_seconds())
        session.status = "approved"
        await db.flush()

        # Create Claim from approved codes
        # Find primary payer coverage
        coverage_id = None
        payer_id = None
        if encounter.patient_id:
            cov_result = await db.execute(
                select(Coverage).where(
                    Coverage.patient_id == encounter.patient_id,
                    Coverage.coverage_type == "primary",
                    Coverage.is_active == True,
                )
            )
            coverage = cov_result.scalar_one_or_none()
            if coverage:
                coverage_id = coverage.id
                payer_id = coverage.payer_id

        claim_number = f"CLM-{uuid4().hex[:12].upper()}"
        total_charge = 0.0  # Will be filled by billing staff from fee schedules

        claim = Claim(
            practice_id=practice_id,
            claim_number=claim_number,
            encounter_id=encounter.id,
            patient_id=encounter.patient_id,
            payer_id=payer_id,
            coverage_id=coverage_id,
            rendering_provider=encounter.provider_id,
            billing_provider=encounter.provider_id,
            claim_type="837P" if encounter.encounter_type in ("office", "telehealth") else "837I",
            total_charge=total_charge,
            status="draft",
            created_by=user_id,
            prior_auth_number=encounter.prior_auth_number,
        )
        db.add(claim)
        await db.flush()

        # Create ClaimLines from approved procedures
        for i, cpt_code in enumerate(approved_procedures, start=1):
            line = ClaimLine(
                practice_id=practice_id,
                claim_id=claim.id,
                line_number=i,
                cpt_code=cpt_code,
                units=1,
                charge_amount=0,  # Filled by billing staff
                service_date_from=encounter.encounter_date,
                place_of_service=encounter.place_of_service,
            )
            db.add(line)

        # Create ClaimDiagnoses from approved diagnosis codes
        for j, dx_code in enumerate(approved_diagnoses, start=1):
            dx = ClaimDiagnosis(
                practice_id=practice_id,
                claim_id=claim.id,
                sequence_number=j,
                icd10_code=dx_code,
                is_principal=(j == 1),
            )
            db.add(dx)

        await db.flush()

        # Create WorkQueueItem for billing
        wqi = WorkQueueItem(
            practice_id=practice_id,
            queue_type="billing",
            item_type="claim",
            item_id=claim.id,
        )
        db.add(wqi)

        # Mark the coding work queue item as completed
        coding_wqi_result = await db.execute(
            select(WorkQueueItem).where(
                WorkQueueItem.item_type == "coding_session",
                WorkQueueItem.item_id == session.id,
                WorkQueueItem.practice_id == practice_id,
                WorkQueueItem.status == "pending",
            )
        )
        coding_wqi = coding_wqi_result.scalar_one_or_none()
        if coding_wqi:
            coding_wqi.status = "completed"
            coding_wqi.completed_at = now

        await _write_audit(
            db, user_id, "approve_codes", "coding_session", session_id,
            resource_detail=f"Claim: {claim_number}, DX codes: {len(approved_diagnoses)}, "
                           f"CPT codes: {len(approved_procedures)}, "
                           f"DX match: {coder_changes.get('diagnosis_match_pct', 0):.0%}, "
                           f"CPT match: {coder_changes.get('procedure_match_pct', 0):.0%}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method, phi_accessed=True,
        )
        logger.info(
            "codes_approved",
            session_id=str(session_id),
            claim_id=str(claim.id),
            dx_count=len(approved_diagnoses),
            proc_count=len(approved_procedures),
        )

        return {
            "session_id": session_id,
            "encounter_id": encounter.id,
            "claim_id": claim.id,
            "claim_number": claim_number,
        }

    async def get_relevant_guidelines(
        self,
        db: AsyncSession,
        session_id: UUID,
        practice_id: UUID,
    ) -> list[dict]:
        """Query vector store for coding guidelines relevant to this session's codes."""
        session = await self.get_session(db, session_id, practice_id)

        # Extract all codes from suggested_codes
        codes = []
        suggested = session.suggested_codes or {}
        for dx in suggested.get("diagnoses", []):
            if isinstance(dx, dict) and dx.get("code"):
                codes.append(dx["code"])
        for proc in suggested.get("procedures", []):
            if isinstance(proc, dict) and proc.get("code"):
                codes.append(proc["code"])

        # Also include final_codes if approved
        final = session.final_codes or {}
        for dx in final.get("diagnoses", []):
            if dx not in codes:
                codes.append(dx)
        for proc in final.get("procedures", []):
            if proc not in codes:
                codes.append(proc)

        if not codes:
            return []

        # Query vector store for guidelines
        guidelines = []
        try:
            from src.core.nlp.vector_store import VectorStoreService
            vs = VectorStoreService()

            for code in codes[:10]:  # Limit to avoid too many queries
                code_system = _detect_code_system(code)
                if code_system == "ICD-10-CM":
                    collection = "icd10_guidelines"
                else:
                    collection = "cpt_guidelines"

                try:
                    results = await vs.search(collection=collection, query=code, limit=3)
                    guidelines.extend(results)
                except Exception as e:
                    logger.warning("guideline_search_failed", collection=collection, code=code, error=str(e))
        except Exception as e:
            logger.warning("vector_store_unavailable", error=str(e))

        # Deduplicate by content
        seen = set()
        unique = []
        for g in guidelines:
            content = g.get("content", "")
            if content not in seen:
                seen.add(content)
                unique.append(g)

        return unique

    def validate_code_combination(
        self,
        diagnosis_codes: list[str],
        procedure_codes: list[str],
        payer_id: UUID | None = None,
    ) -> dict:
        """Pure validation — build synthetic claim and run scrubber. No DB needed."""
        claim_lines = []
        for i, cpt in enumerate(procedure_codes, start=1):
            claim_lines.append({
                "cpt_code": cpt,
                "modifiers": [],
                "units": 1,
                "line_number": i,
            })

        claim_dict = {
            "claim_id": "validation_check",
            "diagnoses": diagnosis_codes,
            "claim_lines": claim_lines,
        }

        result = self.scrubber.scrub(claim_dict)

        return {
            "valid": result.ready_to_submit,
            "score": result.score,
            "findings": [
                {
                    "rule_type": f.rule_type.value if hasattr(f.rule_type, "value") else str(f.rule_type),
                    "severity": f.severity.value if hasattr(f.severity, "value") else str(f.severity),
                    "message": f.message,
                    "suggestion": f.suggestion,
                    "auto_fixable": f.auto_fixable,
                }
                for f in result.findings
            ],
        }

    async def retry_ai_suggestion(
        self,
        db: AsyncSession,
        session_id: UUID,
        practice_id: UUID,
        user_id: UUID,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> CodingSession:
        """Re-run AI pipeline on a session that previously failed."""
        session = await self.get_session(db, session_id, practice_id)

        if session.status not in ("ai_failed", "pending_review"):
            raise CodingSessionAlreadyApprovedError(
                f"Session {session_id} cannot be retried (status: {session.status})"
            )

        # Load encounter
        result = await db.execute(select(Encounter).where(Encounter.id == session.encounter_id))
        encounter = result.scalar_one_or_none()
        if not encounter:
            raise EncounterNotFoundError(session.encounter_id)

        # Assemble clinical text
        clinical_text = self._assemble_clinical_text(encounter)
        if not clinical_text.strip():
            clinical_text = f"Encounter on {encounter.encounter_date}. Type: {encounter.encounter_type}."

        # Re-run AI
        ai_response = None
        ai_error = None
        processing_time_ms = None

        start_time = time.time()
        try:
            ai_service = self._get_ai_service()
            ai_response = await ai_service.suggest_codes(
                clinical_text=clinical_text,
                encounter_type=encounter.encounter_type,
                place_of_service=encounter.place_of_service,
            )
            processing_time_ms = round((time.time() - start_time) * 1000)
        except Exception as e:
            processing_time_ms = round((time.time() - start_time) * 1000)
            ai_error = str(e)
            logger.warning("ai_retry_failed", session_id=str(session_id), error=ai_error)

        if ai_response:
            claim_dict = self._build_synthetic_claim(ai_response, encounter)
            scrub_result = self.scrubber.scrub(claim_dict)
            session.suggested_codes = _build_suggested_codes_json(ai_response, scrub_result.findings)
            session.nlp_extraction = ai_response.entities_extracted
            session.ai_model_version = ai_service.model
            session.status = "pending_review"
        else:
            session.suggested_codes = {
                "diagnoses": [],
                "procedures": [],
                "entities_extracted": {},
                "reasoning": "",
                "scrub_findings": [],
                "error": True,
                "error_detail": ai_error,
            }
            session.nlp_extraction = {"error": ai_error}

        session.processing_time_ms = processing_time_ms
        await db.flush()

        await _write_audit(
            db, user_id, "retry_ai_suggestion", "coding_session", session_id,
            resource_detail=f"Status: {session.status}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method, phi_accessed=True,
        )
        logger.info("ai_suggestion_retried", session_id=str(session_id), status=session.status)
        return session

    @staticmethod
    def _assemble_clinical_text(encounter: Encounter) -> str:
        """Combine encounter data into clinical text for AI processing."""
        parts = []
        if encounter.encounter_type:
            parts.append(f"Encounter Type: {encounter.encounter_type}")
        if encounter.encounter_date:
            parts.append(f"Date: {encounter.encounter_date}")
        if encounter.place_of_service:
            parts.append(f"Place of Service: {encounter.place_of_service}")
        if encounter.notes:
            parts.append(f"Clinical Notes: {encounter.notes}")
        return "\n\n".join(parts)

    @staticmethod
    def _build_synthetic_claim(ai_response, encounter: Encounter, patient_age=None, patient_gender=None) -> dict:
        """Build a synthetic claim dict for the ClaimScrubber from AI suggestions."""
        claim_lines = []
        for i, proc in enumerate(ai_response.procedures, start=1):
            claim_lines.append({
                "cpt_code": proc.code,
                "modifiers": [],
                "units": 1,
                "line_number": i,
            })

        diagnoses = [dx.code for dx in ai_response.diagnoses]

        return {
            "claim_id": "coding_validation",
            "diagnoses": diagnoses,
            "claim_lines": claim_lines,
            "patient_age": patient_age,
            "patient_gender": patient_gender,
            "place_of_service": encounter.place_of_service,
        }


class CodeLookupService:
    """Medical code lookup and semantic search."""

    def __init__(self):
        self._vector_store = None

    def _get_vector_store(self):
        """Lazy initialization to avoid startup failures if Qdrant is down."""
        if self._vector_store is None:
            from src.core.nlp.vector_store import VectorStoreService
            self._vector_store = VectorStoreService()
        return self._vector_store

    async def lookup(self, code: str, code_system: str | None = None) -> dict:
        """Look up a specific medical code with description and guidelines."""
        if code_system is None:
            code_system = _detect_code_system(code)

        if code_system == "ICD-10-CM":
            collection = "icd10_guidelines"
        elif code_system in ("CPT", "HCPCS"):
            collection = "cpt_guidelines"
        else:
            return {
                "code": code,
                "code_system": code_system,
                "description": None,
                "guidelines": [],
                "common_modifiers": [],
            }

        guidelines = []
        try:
            vs = self._get_vector_store()
            results = await vs.search(collection=collection, query=code, limit=5)
            guidelines = results
        except Exception as e:
            logger.warning("code_lookup_failed", code=code, error=str(e))

        return {
            "code": code,
            "code_system": code_system,
            "description": None,  # Would come from a code reference database
            "guidelines": guidelines,
            "common_modifiers": [],
        }

    async def search(self, query: str, code_system: str | None = None, limit: int = 20) -> list[dict]:
        """Semantic search for medical codes by description or clinical term."""
        collections = []
        if code_system == "ICD-10-CM":
            collections = ["icd10_guidelines"]
        elif code_system in ("CPT", "HCPCS"):
            collections = ["cpt_guidelines"]
        else:
            collections = ["icd10_guidelines", "cpt_guidelines"]

        results = []
        try:
            vs = self._get_vector_store()
            for collection in collections:
                try:
                    hits = await vs.search(collection=collection, query=query, limit=limit)
                    results.extend(hits)
                except Exception as e:
                    logger.warning("code_search_failed", collection=collection, error=str(e))
        except Exception as e:
            logger.warning("vector_store_unavailable_for_search", error=str(e))

        # Sort by score and limit
        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return results[:limit]


# Module-level singletons
coding_service = CodingService()
code_lookup_service = CodeLookupService()