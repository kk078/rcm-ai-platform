"""
Billing service layer — Claim creation, scrubbing, submission,
and lifecycle management.

Every write operation creates an AuditLog entry.
Every query enforces tenant isolation via practice_id filtering.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.billing.errors import (
    ClaimNotFoundError,
    ClaimStatusError,
    ClaimSubmissionError,
)
from src.core.rules_engine.scrubber import ClaimScrubber
from src.infrastructure.database.models import (
    AuditLog,
    Claim,
    ClaimDiagnosis,
    ClaimLine,
    ClaimScrubResult,
    Coverage,
    Encounter,
    Payer,
    PayerEnrollment,
    Practice,
    Provider,
    WorkQueueItem,
)
from src.services.edi.parser import Claim837Generator

logger = structlog.get_logger()

# Allowed claim status transitions
VALID_TRANSITIONS = {
    "draft": {"scrubbing", "scrub_failed", "ready"},
    "scrubbing": {"scrub_failed", "ready"},
    "scrub_failed": {"scrubbing", "draft"},
    "ready": {"submitted", "scrub_failed"},
    "submitted": {"accepted", "rejected", "denied", "closed"},
    "accepted": {"paid", "partial_paid", "denied", "closed"},
    "rejected": {"draft", "closed"},
    "paid": {"closed"},
    "partial_paid": {"paid", "closed"},
    "denied": {"appealed", "closed"},
    "appealed": {"paid", "partial_paid", "denied", "closed"},
    "closed": set(),
}


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
    """Create an AuditLog entry."""
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


class ClaimService:
    """Manage claim lifecycle: create, scrub, submit, track."""

    def __init__(self):
        self.scrubber = ClaimScrubber()
        self._ai_service = None

    def _get_ai_service(self):
        """Lazy initialization of AIService."""
        if self._ai_service is None:
            from src.core.nlp.ai_service import AIService
            self._ai_service = AIService()
        return self._ai_service

    async def create_claim(
        self,
        db: AsyncSession,
        user_id: UUID,
        practice_id: UUID,
        data,  # ClaimCreate Pydantic model
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> Claim:
        """Create a claim from encounter data and auto-trigger scrubbing."""
        # Validate encounter
        result = await db.execute(
            select(Encounter).where(
                Encounter.id == data.encounter_id,
                Encounter.practice_id == practice_id,
            )
        )
        encounter = result.scalar_one_or_none()
        if not encounter:
            raise ClaimStatusError(f"Encounter {data.encounter_id} not found in practice {practice_id}")

        # Validate payer
        result = await db.execute(select(Payer).where(Payer.id == data.payer_id))
        payer = result.scalar_one_or_none()
        if not payer:
            raise ClaimStatusError(f"Payer {data.payer_id} not found")

        # Validate coverage
        result = await db.execute(
            select(Coverage).where(
                Coverage.id == data.coverage_id,
                Coverage.patient_id == encounter.patient_id,
                Coverage.is_active == True,
            )
        )
        coverage = result.scalar_one_or_none()
        if not coverage:
            raise ClaimStatusError(f"Coverage {data.coverage_id} not found or inactive")

        # Validate rendering provider
        result = await db.execute(select(Provider).where(Provider.id == data.rendering_provider_id))
        if not result.scalar_one_or_none():
            raise ClaimStatusError(f"Rendering provider {data.rendering_provider_id} not found")

        # Generate claim number
        claim_number = f"CLM-{uuid4().hex[:12].upper()}"

        # Compute total charge
        total_charge = sum(line.charge_amount * line.units for line in data.lines)

        # Create Claim
        claim = Claim(
            practice_id=practice_id,
            claim_number=claim_number,
            encounter_id=data.encounter_id,
            patient_id=encounter.patient_id,
            payer_id=data.payer_id,
            coverage_id=data.coverage_id,
            rendering_provider=data.rendering_provider_id,
            billing_provider=data.billing_provider_id,
            claim_type=data.claim_type,
            frequency_code="1",
            total_charge=total_charge,
            status="draft",
            created_by=user_id,
        )
        db.add(claim)
        await db.flush()

        # Create ClaimLines
        for i, line_data in enumerate(data.lines, start=1):
            line = ClaimLine(
                practice_id=practice_id,
                claim_id=claim.id,
                line_number=i,
                cpt_code=line_data.cpt_code,
                modifier_1=line_data.modifiers[0] if len(line_data.modifiers) > 0 else None,
                modifier_2=line_data.modifiers[1] if len(line_data.modifiers) > 1 else None,
                modifier_3=line_data.modifiers[2] if len(line_data.modifiers) > 2 else None,
                modifier_4=line_data.modifiers[3] if len(line_data.modifiers) > 3 else None,
                units=line_data.units,
                charge_amount=line_data.charge_amount,
                service_date_from=line_data.service_date_from,
                service_date_to=line_data.service_date_to,
                place_of_service=line_data.place_of_service or encounter.place_of_service,
                ndc_code=line_data.ndc_code,
                revenue_code=line_data.revenue_code,
            )
            db.add(line)

        # Create ClaimDiagnoses
        for j, dx_code in enumerate(data.diagnosis_codes, start=1):
            dx = ClaimDiagnosis(
                practice_id=practice_id,
                claim_id=claim.id,
                sequence_number=j,
                icd10_code=dx_code,
                is_principal=(j == 1),
            )
            db.add(dx)

        await db.flush()

        # Auto-trigger scrubbing
        try:
            scrub_result = await self._scrub_claim_internal(db, claim, data.lines)
            if scrub_result.ready_to_submit:
                claim.status = "ready"
            else:
                claim.status = "scrub_failed"
            await db.flush()
        except Exception as e:
            logger.warning("auto_scrub_failed", claim_id=str(claim.id), error=str(e))
            # Keep status as "draft" if scrub fails
            claim.status = "scrub_failed"
            await db.flush()

        # Create WorkQueueItem
        wqi = WorkQueueItem(
            practice_id=practice_id,
            queue_type="billing",
            item_type="claim",
            item_id=claim.id,
        )
        db.add(wqi)

        # Set timely filing deadline
        if payer and payer.timely_filing_days:
            claim.timely_filing_deadline = date.fromordinal(
                encounter.encounter_date.toordinal() + payer.timely_filing_days
            )
            await db.flush()

        await _write_audit(
            db, user_id, "create_claim", "claim", claim.id,
            resource_detail=f"Claim: {claim_number}, Type: {data.claim_type}, Total: ${total_charge:.2f}, Status: {claim.status}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method, phi_accessed=True,
        )
        logger.info("claim_created", claim_id=str(claim.id), claim_number=claim_number, status=claim.status)
        return claim

    async def scrub_claim(
        self,
        db: AsyncSession,
        user_id: UUID,
        claim_id: UUID,
        practice_id: UUID,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> dict:
        """Run the claim scrubbing pipeline on an existing claim."""
        claim = await self._get_claim_or_raise(db, claim_id, practice_id)

        # Only scrub claims in draft or scrub_failed status
        if claim.status not in ("draft", "scrub_failed"):
            raise ClaimStatusError(f"Cannot scrub claim in '{claim.status}' status. Must be 'draft' or 'scrub_failed'.")

        claim.status = "scrubbing"
        await db.flush()

        # Load related data
        lines_result = await db.execute(
            select(ClaimLine).where(ClaimLine.claim_id == claim_id)
        )
        lines = list(lines_result.scalars().all())

        dx_result = await db.execute(
            select(ClaimDiagnosis).where(ClaimDiagnosis.claim_id == claim_id)
        )
        diagnoses = list(dx_result.scalars().all())

        # Build claim dict for scrubber
        claim_dict = self._build_claim_dict_for_scrubber(claim, lines, diagnoses)

        # Load payer rules if available
        payer_rules = await self._load_payer_rules(db, claim.payer_id, practice_id)

        # Run deterministic scrubber
        scrub_result = self.scrubber.scrub(claim_dict, payer_rules=payer_rules)

        # Delete old scrub results for this claim
        old_results = await db.execute(
            select(ClaimScrubResult).where(ClaimScrubResult.claim_id == claim_id)
        )
        for old in old_results.scalars().all():
            await db.delete(old)
        await db.flush()

        # Create new ClaimScrubResult records
        for finding in scrub_result.findings:
            result_record = ClaimScrubResult(
                practice_id=practice_id,
                claim_id=claim_id,
                claim_line_id=None,  # Could map to specific line
                rule_type=finding.rule_type.value if hasattr(finding.rule_type, "value") else str(finding.rule_type),
                severity=finding.severity.value if hasattr(finding.severity, "value") else str(finding.severity),
                message=finding.message,
                suggestion=finding.suggestion,
                auto_fixable=finding.auto_fixable,
                rule_reference=finding.rule_reference,
            )
            db.add(result_record)

        # Try AI risk analysis (graceful degradation)
        ai_denial_risk = claim.denial_risk_score or 0.0
        try:
            ai_service = self._get_ai_service()
            # Build claim data dict for AI
            ai_claim_data = {
                "claim_id": str(claim.id),
                "claim_type": claim.claim_type,
                "total_charge": claim.total_charge,
                "patient_age": None,  # Would need patient lookup
                "diagnoses": [dx.icd10_code for dx in diagnoses],
                "claim_lines": [
                    {"cpt_code": line.cpt_code, "units": line.units, "charge_amount": line.charge_amount}
                    for line in lines
                ],
            }
            ai_insight = await ai_service.analyze_claim_risk(
                claim_data=ai_claim_data,
                payer_name=payer.payer_name if await db.execute(select(Payer).where(Payer.id == claim.payer_id)).scalar_one_or_none() else "Unknown",
            )
            ai_denial_risk = ai_insight.denial_probability
            claim.denial_risk_score = ai_denial_risk
        except Exception as e:
            logger.warning("ai_risk_analysis_skipped", claim_id=str(claim_id), error=str(e))

        # Update claim
        claim.scrub_score = scrub_result.score
        claim.status = "ready" if scrub_result.ready_to_submit else "scrub_failed"
        await db.flush()

        await _write_audit(
            db, user_id, "scrub_claim", "claim", claim_id,
            resource_detail=f"Score: {scrub_result.score}, Errors: {len(scrub_result.errors)}, "
                           f"Warnings: {len(scrub_result.warnings)}, Status: {claim.status}, "
                           f"AI risk: {ai_denial_risk:.2f}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method, phi_accessed=True,
        )
        logger.info("claim_scrubbed", claim_id=str(claim_id), score=scrub_result.score, status=claim.status)

        return {
            "claim_id": claim_id,
            "scrub_score": scrub_result.score,
            "errors": [
                {
                    "rule_type": f.rule_type.value if hasattr(f.rule_type, "value") else str(f.rule_type),
                    "severity": f.severity.value if hasattr(f.severity, "value") else str(f.severity),
                    "message": f.message,
                    "suggestion": f.suggestion,
                    "auto_fixable": f.auto_fixable,
                    "claim_line_number": f.claim_line_number,
                }
                for f in scrub_result.errors
            ],
            "warnings": [
                {
                    "rule_type": f.rule_type.value if hasattr(f.rule_type, "value") else str(f.rule_type),
                    "severity": f.severity.value if hasattr(f.severity, "value") else str(f.severity),
                    "message": f.message,
                    "suggestion": f.suggestion,
                    "auto_fixable": f.auto_fixable,
                    "claim_line_number": f.claim_line_number,
                }
                for f in scrub_result.warnings
            ],
            "info": [
                {
                    "rule_type": f.rule_type.value if hasattr(f.rule_type, "value") else str(f.rule_type),
                    "severity": f.severity.value if hasattr(f.severity, "value") else str(f.severity),
                    "message": f.message,
                    "suggestion": f.suggestion,
                    "auto_fixable": f.auto_fixable,
                    "claim_line_number": f.claim_line_number,
                }
                for f in scrub_result.findings if f.severity.value == "info" or (hasattr(f.severity, "value") and f.severity.value == "info")
            ],
            "denial_risk_score": ai_denial_risk,
            "ready_to_submit": scrub_result.ready_to_submit,
        }

    async def submit_claim(
        self,
        db: AsyncSession,
        user_id: UUID,
        claim_id: UUID,
        practice_id: UUID,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> dict:
        """Submit a scrubbed claim to the clearinghouse."""
        claim = await self._get_claim_or_raise(db, claim_id, practice_id)

        if claim.status != "ready":
            raise ClaimStatusError(
                f"Cannot submit claim in '{claim.status}' status. Must be 'ready'."
            )

        # Generate EDI 837
        edi_content = self._generate_edi_837(claim, db)

        # Update claim status
        claim.status = "submitted"
        claim.submission_date = datetime.now(timezone.utc)

        # Get clearinghouse config from practice
        practice_result = await db.execute(select(Practice).where(Practice.id == practice_id))
        practice = practice_result.scalar_one_or_none()

        if practice and practice.default_clearinghouse:
            claim.clearinghouse_id = practice.default_clearinghouse

        # Generate clearinghouse reference (stub for now)
        claim.clearinghouse_ref = f"CH-{uuid4().hex[:8].upper()}"

        await db.flush()

        # Create follow-up work queue item
        wqi = WorkQueueItem(
            practice_id=practice_id,
            queue_type="follow_up",
            item_type="claim",
            item_id=claim.id,
        )
        db.add(wqi)

        await _write_audit(
            db, user_id, "submit_claim", "claim", claim_id,
            resource_detail=f"Claim: {claim.claim_number}, Clearinghouse: {claim.clearinghouse_id}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method, phi_accessed=True,
        )
        logger.info("claim_submitted", claim_id=str(claim_id), claim_number=claim.claim_number)

        return {
            "claim_id": claim_id,
            "claim_number": claim.claim_number,
            "edi_content": edi_content,
            "clearinghouse_id": claim.clearinghouse_id,
            "clearinghouse_ref": claim.clearinghouse_ref,
            "status": claim.status,
        }

    async def batch_submit(
        self,
        db: AsyncSession,
        user_id: UUID,
        practice_id: UUID,
        claim_ids: list[UUID],
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> dict:
        """Submit multiple ready claims in a single batch."""
        submitted = []
        skipped = []

        for cid in claim_ids:
            result = await db.execute(
                select(Claim).where(Claim.id == cid, Claim.practice_id == practice_id)
            )
            claim = result.scalar_one_or_none()
            if not claim:
                skipped.append({"claim_id": str(cid), "reason": "not found"})
                continue
            if claim.status != "ready":
                skipped.append({"claim_id": str(cid), "reason": f"status is '{claim.status}', must be 'ready'"})
                continue

            claim.status = "submitted"
            claim.submission_date = datetime.now(timezone.utc)
            claim.clearinghouse_ref = f"CH-{uuid4().hex[:8].upper()}"
            submitted.append(str(cid))

        await db.flush()

        await _write_audit(
            db, user_id, "batch_submit_claims", "claim", None,
            resource_detail=f"Submitted: {len(submitted)}, Skipped: {len(skipped)}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method, phi_accessed=True,
        )
        logger.info("batch_submit", submitted=len(submitted), skipped=len(skipped))

        return {
            "submitted_count": len(submitted),
            "submitted_ids": submitted,
            "skipped_count": len(skipped),
            "skipped": skipped,
        }

    async def void_claim(
        self,
        db: AsyncSession,
        user_id: UUID,
        claim_id: UUID,
        practice_id: UUID,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> Claim:
        """Void a submitted claim."""
        claim = await self._get_claim_or_raise(db, claim_id, practice_id)

        if claim.status not in ("submitted", "accepted"):
            raise ClaimStatusError(f"Cannot void claim in '{claim.status}' status. Must be 'submitted' or 'accepted'.")

        claim.frequency_code = "8"  # Void/cancel
        claim.status = "closed"
        await db.flush()

        await _write_audit(
            db, user_id, "void_claim", "claim", claim_id,
            resource_detail=f"Claim: {claim.claim_number} voided",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method, phi_accessed=True,
        )
        logger.info("claim_voided", claim_id=str(claim_id))
        return claim

    async def submit_corrected(
        self,
        db: AsyncSession,
        user_id: UUID,
        claim_id: UUID,
        practice_id: UUID,
        data,  # ClaimCreate Pydantic model
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> Claim:
        """Submit a corrected claim (frequency code 7)."""
        original_claim = await self._get_claim_or_raise(db, claim_id, practice_id)

        # Create the corrected claim using the normal flow
        corrected = await self.create_claim(
            db=db, user_id=user_id, practice_id=practice_id, data=data,
            ip_address=ip_address, request_path=request_path,
            request_method=request_method,
        )

        # Set frequency code to 7 (corrected)
        corrected.frequency_code = "7"
        await db.flush()

        await _write_audit(
            db, user_id, "submit_corrected_claim", "claim", corrected.id,
            resource_detail=f"Corrected claim for original {original_claim.claim_number}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method, phi_accessed=True,
        )
        logger.info("corrected_claim_created", claim_id=str(corrected.id), original_claim_id=str(claim_id))
        return corrected

    async def list_claims(
        self,
        db: AsyncSession,
        practice_id: UUID,
        status: str | None = None,
        payer_id: UUID | None = None,
        patient_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[Claim]:
        """List claims with filtering and pagination."""
        query = select(Claim).where(Claim.practice_id == practice_id)
        if status:
            query = query.where(Claim.status == status)
        if payer_id:
            query = query.where(Claim.payer_id == payer_id)
        if patient_id:
            query = query.where(Claim.patient_id == patient_id)
        if date_from:
            query = query.where(Claim.created_at >= date_from)
        if date_to:
            query = query.where(Claim.created_at <= date_to)
        query = query.order_by(Claim.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_claim(
        self,
        db: AsyncSession,
        claim_id: UUID,
        practice_id: UUID,
    ) -> Claim:
        """Get a single claim with tenant isolation."""
        return await self._get_claim_or_raise(db, claim_id, practice_id)

    async def get_scrub_results(
        self,
        db: AsyncSession,
        claim_id: UUID,
        practice_id: UUID,
    ) -> list[ClaimScrubResult]:
        """Get scrub results for a claim."""
        # Verify claim exists and belongs to practice
        await self._get_claim_or_raise(db, claim_id, practice_id)
        result = await db.execute(
            select(ClaimScrubResult).where(ClaimScrubResult.claim_id == claim_id)
        )
        return list(result.scalars().all())

    async def get_claim_history(
        self,
        db: AsyncSession,
        claim_id: UUID,
        practice_id: UUID,
    ) -> dict:
        """Get claim lifecycle history from audit log."""
        # Verify claim exists and belongs to practice
        claim = await self._get_claim_or_raise(db, claim_id, practice_id)
        result = await db.execute(
            select(AuditLog).where(
                AuditLog.resource_type == "claim",
                AuditLog.resource_id == claim_id,
            ).order_by(AuditLog.created_at)
        )
        audit_entries = result.scalars().all()

        return {
            "claim_id": str(claim_id),
            "claim_number": claim.claim_number,
            "current_status": claim.status,
            "history": [
                {
                    "action": entry.action,
                    "detail": entry.resource_detail,
                    "user_id": str(entry.user_id),
                    "timestamp": entry.created_at.isoformat() if entry.created_at else None,
                }
                for entry in audit_entries
            ],
        }

    # ── Helper Methods ────────────────────────────────────────────────

    async def _get_claim_or_raise(
        self, db: AsyncSession, claim_id: UUID, practice_id: UUID
    ) -> Claim:
        """Load a claim with tenant isolation check."""
        result = await db.execute(
            select(Claim).where(
                Claim.id == claim_id,
                Claim.practice_id == practice_id,
            )
        )
        claim = result.scalar_one_or_none()
        if not claim:
            raise ClaimNotFoundError(claim_id)
        return claim

    async def _scrub_claim_internal(
        self, db: AsyncSession, claim: Claim, line_data_list
    ) -> "ScrubResult":
        """Run the scrubber on a claim (used during create_claim)."""
        # Build a simplified claim dict for the scrubber
        claim_dict = {
            "claim_id": str(claim.id),
            "diagnoses": [],
            "claim_lines": [],
            "place_of_service": None,
            "service_date": None,
        }

        # Add lines
        for line_data in line_data_list:
            claim_dict["claim_lines"].append({
                "cpt_code": line_data.cpt_code,
                "modifiers": line_data.modifiers,
                "units": line_data.units,
                "line_number": len(claim_dict["claim_lines"]) + 1,
            })

        return self.scrubber.scrub(claim_dict)

    def _build_claim_dict_for_scrubber(
        self, claim: Claim, lines: list[ClaimLine], diagnoses: list[ClaimDiagnosis]
    ) -> dict:
        """Convert ORM objects to the dict format ClaimScrubber expects."""
        claim_lines = []
        for line in lines:
            claim_lines.append({
                "cpt_code": line.cpt_code,
                "modifiers": [
                    m for m in [line.modifier_1, line.modifier_2, line.modifier_3, line.modifier_4]
                    if m is not None
                ],
                "units": line.units or 1,
                "charge_amount": line.charge_amount,
                "line_number": line.line_number,
                "place_of_service": line.place_of_service,
                "icd_pointers": [],
            })

        # Add diagnosis pointers to lines
        for line_dict in claim_lines:
            for i, dx in enumerate(diagnoses, start=1):
                if i <= 4:
                    line_dict.setdefault("icd_pointers", []).append(dx.icd10_code)

        return {
            "claim_id": str(claim.id),
            "claim_lines": claim_lines,
            "diagnoses": [dx.icd10_code for dx in diagnoses],
            "place_of_service": claim.claim_type == "837P" and "11" or "21",
            "service_date": None,
            "payer_timely_filing_days": 365,
        }

    async def _load_payer_rules(
        self, db: AsyncSession, payer_id: UUID | None, practice_id: UUID
    ) -> list[dict] | None:
        """Load payer-specific billing rules from PayerEnrollment and PayerRule tables."""
        # PayerRule table doesn't exist yet; return None
        # This is a placeholder for future payer rule loading
        return None

    def _generate_edi_837(self, claim: Claim, db) -> str:
        """Generate EDI 837 envelope for a claim using Claim837Generator."""
        from src.config import get_settings
        settings = get_settings()

        generator = Claim837Generator(
            sender_id=settings.clearinghouse_sender_id or "SENDER",
            receiver_id=settings.clearinghouse_receiver_id or "RECEIVER",
        )

        claim_data = {
            "claim_number": claim.claim_number,
            "claim_type": claim.claim_type,
            "total_charge": claim.total_charge,
            "frequency_code": claim.frequency_code,
        }

        edi_content = generator.generate_837p([claim_data])
        logger.info("edi_837_generated", claim_id=str(claim.id), claim_number=claim.claim_number)
        return edi_content


# Module-level singleton
claim_service = ClaimService()