"""
Payment posting service — ERA/835 parsing, claim matching,
auto-posting, underpayment detection, and denial routing.

Every write operation creates an AuditLog entry.
Every query enforces tenant isolation via practice_id filtering.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.payments.errors import (
    BatchNotFoundError,
    BatchStatusError,
    ClaimMatchError,
    ERAParseError,
    PaymentLineNotFoundError,
    UnderpaymentDisputeError,
)
from src.infrastructure.database.models import (
    Adjustment,
    AuditLog,
    Claim,
    ClaimLine,
    Denial,
    FeeScheduleRate,
    Payer,
    PayerEnrollment,
    PaymentBatch,
    PaymentLine,
    WorkQueueItem,
)
from src.services.edi.parser import ERA835Parser, AdjustmentGroupCode

logger = structlog.get_logger()

# Underpayment tolerance: payments within 5% of fee schedule are not flagged
UNDERPAYMENT_TOLERANCE = 0.05

# Auto-posting confidence threshold
AUTO_POST_CONFIDENCE = 0.95


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


class PaymentService:
    """Manage payment posting: ERA parsing, matching, auto-posting, underpayment detection."""

    def __init__(self):
        self._era_parser = ERA835Parser()

    # ── ERA Upload & Processing ──────────────────────────────────────

    async def upload_and_process_era(
        self,
        db: AsyncSession,
        user_id: UUID,
        practice_id: UUID,
        era_content: str,
        filename: str | None = None,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> PaymentBatch:
        """Parse an ERA/835 file, match payment lines to claims,
        detect underpayments, route denials, and auto-post clean matches."""
        # Step 1: Parse the ERA
        try:
            batch_data = self._era_parser.parse(era_content)
        except (ValueError, KeyError, IndexError) as e:
            raise ERAParseError(f"Failed to parse ERA file: {e}")

        # Step 2: Resolve or create payer
        payer = await self._resolve_payer(db, batch_data.payer_id, batch_data.payer_name)
        await db.flush()

        # Step 3: Create PaymentBatch
        payment_method = self._map_payment_method(batch_data.payment_method)
        batch = PaymentBatch(
            practice_id=practice_id,
            payer_id=payer.id,
            check_number=batch_data.check_number or None,
            payment_method=payment_method,
            total_paid=float(batch_data.total_paid),
            total_claims=batch_data.total_claims,
            production_date=batch_data.production_date,
            status="received",
        )
        db.add(batch)
        await db.flush()

        # Step 4: Transition to processing
        batch.status = "processing"
        await db.flush()

        # Step 5: Process each claim
        auto_posted_count = 0
        exception_count = 0
        denial_count = 0
        underpayment_count = 0

        for edi_claim in batch_data.claims:
            # For each EDIServiceLine, create a PaymentLine
            for svc_line in edi_claim.service_lines:
                payment_line = PaymentLine(
                    practice_id=practice_id,
                    batch_id=batch.id,
                    claim_number_reported=edi_claim.claim_id,
                    service_date=svc_line.service_date_from,
                    cpt_code=svc_line.procedure_code,
                    billed_amount=float(svc_line.charge_amount),
                    allowed_amount=float(svc_line.allowed_amount) if svc_line.allowed_amount else None,
                    paid_amount=float(svc_line.paid_amount),
                    patient_responsibility=float(svc_line.patient_responsibility),
                    match_status="unmatched",
                    match_confidence=None,
                    is_underpaid=False,
                    underpayment_amount=None,
                )
                db.add(payment_line)
                await db.flush()

                # Create Adjustment records for service line adjustments
                for adj in svc_line.adjustments:
                    adjustment = Adjustment(
                        practice_id=practice_id,
                        payment_line_id=payment_line.id,
                        group_code=adj.group_code.value if hasattr(adj.group_code, "value") else str(adj.group_code),
                        reason_code=adj.reason_code,
                        amount=float(adj.amount),
                        remark_codes=adj.remark_codes,
                        is_denial=adj.is_denial,
                    )
                    db.add(adjustment)

                # Also create Adjustment records for claim-level adjustments
                for adj in edi_claim.claim_adjustments:
                    # Only create claim-level adjustments once (not per service line)
                    if svc_line is edi_claim.service_lines[0]:
                        adjustment = Adjustment(
                            practice_id=practice_id,
                            payment_line_id=payment_line.id,
                            group_code=adj.group_code.value if hasattr(adj.group_code, "value") else str(adj.group_code),
                            reason_code=adj.reason_code,
                            amount=float(adj.amount),
                            remark_codes=adj.remark_codes,
                            is_denial=adj.is_denial,
                        )
                        db.add(adjustment)

                await db.flush()

                # Step 5a: Attempt claim matching
                claim, confidence = await self._match_payment_line_to_claim(
                    db, practice_id, payer.id,
                    edi_claim.claim_id,
                    float(edi_claim.total_charge),
                    edi_claim.patient_name,
                )
                if claim:
                    payment_line.claim_id = claim.id
                    payment_line.patient_id = claim.patient_id
                    payment_line.match_confidence = confidence

                    # Try to match to a specific ClaimLine by CPT code
                    if payment_line.cpt_code:
                        cl_result = await db.execute(
                            select(ClaimLine).where(
                                ClaimLine.claim_id == claim.id,
                                ClaimLine.cpt_code == payment_line.cpt_code,
                            )
                        )
                        claim_line = cl_result.scalar_one_or_none()
                        if claim_line:
                            payment_line.claim_line_id = claim_line.id

                    if confidence >= 0.85:
                        payment_line.match_status = "matched" if confidence >= AUTO_POST_CONFIDENCE else "partial"
                    else:
                        payment_line.match_status = "partial"
                else:
                    payment_line.match_status = "unmatched"
                    # Create work queue item for unmatched
                    wqi = WorkQueueItem(
                        practice_id=practice_id,
                        queue_type="posting",
                        item_type="payment_line",
                        item_id=payment_line.id,
                    )
                    db.add(wqi)

                # Step 5b: Underpayment detection
                if claim and confidence >= AUTO_POST_CONFIDENCE:
                    is_under, under_amount = await self._detect_underpayment(
                        db, practice_id, payer.id, payment_line, svc_line,
                    )
                    if is_under:
                        payment_line.is_underpaid = True
                        payment_line.underpayment_amount = under_amount
                        payment_line.match_status = "exception"
                        underpayment_count += 1
                        # Create work queue item for underpayment
                        wqi = WorkQueueItem(
                            practice_id=practice_id,
                            queue_type="posting",
                            item_type="payment_line",
                            item_id=payment_line.id,
                            priority=80,
                        )
                        db.add(wqi)

                # Step 5c: Denial routing
                if claim and edi_claim.has_denials:
                    denials_created = await self._route_denials(
                        db, practice_id, payer.id, claim, payment_line, edi_claim,
                    )
                    denial_count += len(denials_created)

                # Step 5d: Auto-posting
                if claim and confidence >= AUTO_POST_CONFIDENCE:
                    if not payment_line.is_underpaid and not edi_claim.has_denials:
                        posted = await self._auto_post_line(db, claim, payment_line, edi_claim)
                        if posted:
                            auto_posted_count += 1

                await db.flush()

        # Step 6: Finalize batch status
        if exception_count == 0 and underpayment_count == 0:
            # Check if all lines are matched
            lines_result = await db.execute(
                select(PaymentLine).where(PaymentLine.batch_id == batch.id)
            )
            all_lines = list(lines_result.scalars().all())
            unmatched = [l for l in all_lines if l.match_status in ("unmatched", "partial", "exception")]
            if not unmatched:
                batch.status = "posted"
            else:
                batch.status = "processing"  # Stay in processing for manual resolution
        else:
            batch.status = "processing"

        await db.flush()

        await _write_audit(
            db, user_id, "process_era", "payment_batch", batch.id,
            resource_detail=f"Batch: {batch.check_number or filename}, "
                           f"Claims: {batch.total_claims}, Auto-posted: {auto_posted_count}, "
                           f"Denials: {denial_count}, Underpayments: {underpayment_count}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method, phi_accessed=True,
        )
        logger.info(
            "era_processed",
            batch_id=str(batch.id),
            auto_posted=auto_posted_count,
            denials=denial_count,
            underpayments=underpayment_count,
        )
        return batch

    # ── Batch Query Methods ────────────────────────────────────────────

    async def list_batches(
        self,
        db: AsyncSession,
        practice_id: UUID,
        status: str | None = None,
        payer_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[PaymentBatch]:
        """List payment batches with filtering and pagination."""
        query = select(PaymentBatch).where(PaymentBatch.practice_id == practice_id)
        if status:
            query = query.where(PaymentBatch.status == status)
        if payer_id:
            query = query.where(PaymentBatch.payer_id == payer_id)
        if date_from:
            query = query.where(PaymentBatch.production_date >= date_from)
        if date_to:
            query = query.where(PaymentBatch.production_date <= date_to)
        query = query.order_by(PaymentBatch.production_date.desc()).offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_batch(
        self,
        db: AsyncSession,
        batch_id: UUID,
        practice_id: UUID,
    ) -> PaymentBatch:
        """Get a single payment batch with tenant isolation."""
        return await self._get_batch_or_raise(db, batch_id, practice_id)

    async def get_batch_lines(
        self,
        db: AsyncSession,
        batch_id: UUID,
        practice_id: UUID,
        match_status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[PaymentLine]:
        """Get payment lines within a batch, optionally filtered by match status."""
        await self._get_batch_or_raise(db, batch_id, practice_id)
        query = select(PaymentLine).where(
            PaymentLine.batch_id == batch_id,
            PaymentLine.practice_id == practice_id,
        )
        if match_status:
            query = query.where(PaymentLine.match_status == match_status)
        query = query.order_by(PaymentLine.created_at).offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        return list(result.scalars().all())

    # ── Batch Posting ──────────────────────────────────────────────────

    async def post_batch(
        self,
        db: AsyncSession,
        user_id: UUID,
        batch_id: UUID,
        practice_id: UUID,
        auto_only: bool = True,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> dict:
        """Post matched payments. If auto_only=True, only posts high-confidence matches."""
        batch = await self._get_batch_or_raise(db, batch_id, practice_id)

        if batch.status not in ("received", "processing"):
            raise BatchStatusError(f"Cannot post batch in '{batch.status}' status. Must be 'received' or 'processing'.")

        # Load all payment lines for this batch
        lines_result = await db.execute(
            select(PaymentLine).where(
                PaymentLine.batch_id == batch_id,
                PaymentLine.practice_id == practice_id,
            )
        )
        lines = list(lines_result.scalars().all())

        # Filter eligible lines
        if auto_only:
            eligible = [l for l in lines if l.match_status == "matched" and l.claim_id is not None]
        else:
            eligible = [l for l in lines if l.match_status in ("matched", "partial") and l.claim_id is not None]

        posted_count = 0
        for line in eligible:
            # Load the claim
            claim_result = await db.execute(
                select(Claim).where(Claim.id == line.claim_id)
            )
            claim = claim_result.scalar_one_or_none()
            if not claim:
                continue

            # Update claim financials
            claim.total_paid = (claim.total_paid or 0) + line.paid_amount

            # Load adjustments for this line
            adj_result = await db.execute(
                select(Adjustment).where(Adjustment.payment_line_id == line.id)
            )
            adjustments = list(adj_result.scalars().all())
            contractual = sum(a.amount for a in adjustments if a.group_code == "CO")
            patient_resp = sum(a.amount for a in adjustments if a.group_code == "PR")
            claim.total_adjusted = (claim.total_adjusted or 0) + contractual
            claim.patient_responsibility = (claim.patient_responsibility or 0) + patient_resp

            # Update claim status
            if claim.total_paid >= claim.total_charge:
                claim.status = "paid"
            else:
                claim.status = "partial_paid"

            # Update matching claim line amounts
            if line.claim_line_id:
                cl_result = await db.execute(
                    select(ClaimLine).where(ClaimLine.id == line.claim_line_id)
                )
                claim_line = cl_result.scalar_one_or_none()
                if claim_line:
                    claim_line.paid_amount = line.paid_amount
                    if line.allowed_amount:
                        claim_line.allowed_amount = line.allowed_amount

            line.match_status = "matched"
            posted_count += 1

        # Update batch status
        batch.status = "posted"
        batch.posted_by = user_id
        batch.posted_date = datetime.now(timezone.utc)
        batch.auto_posted = auto_only

        await db.flush()

        await _write_audit(
            db, user_id, "post_payment_batch", "payment_batch", batch_id,
            resource_detail=f"Posted {posted_count} of {len(lines)} lines, auto_only={auto_only}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method, phi_accessed=True,
        )
        logger.info("batch_posted", batch_id=str(batch_id), posted=posted_count, total=len(lines))

        return {
            "batch_id": batch_id,
            "posted_count": posted_count,
            "total_lines": len(lines),
            "status": batch.status,
        }

    # ── Manual Matching ───────────────────────────────────────────────

    async def manual_match(
        self,
        db: AsyncSession,
        user_id: UUID,
        line_id: UUID,
        claim_id: UUID,
        practice_id: UUID,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> PaymentLine:
        """Manually match an unmatched payment line to a claim."""
        line = await self._get_line_or_raise(db, line_id, practice_id)

        # Validate the target claim exists and belongs to practice
        claim_result = await db.execute(
            select(Claim).where(Claim.id == claim_id, Claim.practice_id == practice_id)
        )
        claim = claim_result.scalar_one_or_none()
        if not claim:
            raise ClaimMatchError(f"Claim {claim_id} not found in practice {practice_id}")

        # Update the payment line
        line.claim_id = claim_id
        line.patient_id = claim.patient_id
        line.match_status = "matched"
        line.match_confidence = 1.0  # Manual match is authoritative

        # Try to resolve claim_line_id from CPT code
        if line.cpt_code:
            cl_result = await db.execute(
                select(ClaimLine).where(
                    ClaimLine.claim_id == claim_id,
                    ClaimLine.cpt_code == line.cpt_code,
                )
            )
            claim_line = cl_result.scalar_one_or_none()
            if claim_line:
                line.claim_line_id = claim_line.id

        await _write_audit(
            db, user_id, "manual_match_payment", "payment_line", line_id,
            resource_detail=f"Matched to claim {claim.claim_number}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method, phi_accessed=True,
        )
        logger.info("manual_match", line_id=str(line_id), claim_id=str(claim_id))
        return line

    # ── Underpayment Dispute ──────────────────────────────────────────

    async def dispute_underpayment(
        self,
        db: AsyncSession,
        user_id: UUID,
        line_id: UUID,
        expected_amount: float,
        notes: str,
        practice_id: UUID,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> dict:
        """Flag an underpayment for dispute with the payer."""
        line = await self._get_line_or_raise(db, line_id, practice_id)

        if not line.is_underpaid:
            raise UnderpaymentDisputeError("Payment line is not flagged as underpaid")

        # Update underpayment amount with the user's expected amount
        line.underpayment_amount = expected_amount - line.paid_amount
        line.match_status = "exception"

        # Create a work queue item for the underpayment dispute
        wqi = WorkQueueItem(
            practice_id=practice_id,
            queue_type="follow_up",
            item_type="payment_line",
            item_id=line.id,
            priority=80,
        )
        db.add(wqi)

        await _write_audit(
            db, user_id, "dispute_underpayment", "payment_line", line_id,
            resource_detail=f"Expected: {expected_amount}, Paid: {line.paid_amount}, "
                           f"Underpayment: {line.underpayment_amount}, Notes: {notes}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method, phi_accessed=True,
        )
        logger.info("underpayment_disputed", line_id=str(line_id), expected=expected_amount, paid=line.paid_amount)

        return {
            "line_id": str(line_id),
            "paid_amount": line.paid_amount,
            "expected_amount": expected_amount,
            "underpayment_amount": line.underpayment_amount,
            "status": "disputed",
        }

    # ── Reconciliation ─────────────────────────────────────────────────

    async def get_reconciliation_report(
        self,
        db: AsyncSession,
        practice_id: UUID,
        period: str,  # YYYY-MM format
    ) -> dict:
        """Generate a monthly reconciliation report."""
        try:
            year, month = int(period[:4]), int(period[5:7])
        except (ValueError, IndexError):
            raise PaymentError(f"Invalid period format: {period}. Use YYYY-MM.", status_code=422)

        date_from = date(year, month, 1)
        date_to = date(year + (1 if month == 12 else 0), (month % 12) + 1, 1)

        # Total payments received
        received_result = await db.execute(
            select(func.sum(PaymentBatch.total_paid)).where(
                PaymentBatch.practice_id == practice_id,
                PaymentBatch.production_date >= date_from,
                PaymentBatch.production_date < date_to,
            )
        )
        total_received = float(received_result.scalar() or 0)

        # Total payments posted
        posted_result = await db.execute(
            select(func.sum(PaymentBatch.total_paid)).where(
                PaymentBatch.practice_id == practice_id,
                PaymentBatch.production_date >= date_from,
                PaymentBatch.production_date < date_to,
                PaymentBatch.status == "posted",
            )
        )
        total_posted = float(posted_result.scalar() or 0)

        # Unmatched payments
        unmatched_result = await db.execute(
            select(func.count(PaymentLine.id), func.sum(PaymentLine.paid_amount)).where(
                PaymentLine.practice_id == practice_id,
                PaymentLine.match_status == "unmatched",
            )
        )
        unmatched_row = unmatched_result.one()
        unmatched_count = unmatched_row[0] or 0
        unmatched_amount = float(unmatched_row[1] or 0)

        # Underpayments
        underpayment_result = await db.execute(
            select(func.count(PaymentLine.id), func.sum(PaymentLine.underpayment_amount)).where(
                PaymentLine.practice_id == practice_id,
                PaymentLine.is_underpaid == True,
            )
        )
        underpayment_row = underpayment_result.one()
        underpayment_count = underpayment_row[0] or 0
        underpayments_detected = float(underpayment_row[1] or 0)

        # Denials routed
        denials_result = await db.execute(
            select(func.count(Denial.id), func.sum(Denial.denial_amount)).where(
                Denial.practice_id == practice_id,
                Denial.denial_date >= date_from,
                Denial.denial_date < date_to,
            )
        )
        denials_row = denials_result.one()
        denials_routed = denials_row[0] or 0
        denials_amount = float(denials_row[1] or 0)

        # Auto-post rate
        total_lines_result = await db.execute(
            select(func.count(PaymentLine.id)).where(
                PaymentLine.practice_id == practice_id,
            )
        )
        total_lines = total_lines_result.scalar() or 1
        matched_lines_result = await db.execute(
            select(func.count(PaymentLine.id)).where(
                PaymentLine.practice_id == practice_id,
                PaymentLine.match_status == "matched",
            )
        )
        matched_lines = matched_lines_result.scalar() or 0
        auto_post_rate = round((matched_lines / total_lines * 100), 2) if total_lines > 0 else 0.0

        return {
            "period": period,
            "total_payments_received": total_received,
            "total_payments_posted": total_posted,
            "unmatched_payments": unmatched_amount,
            "unmatched_count": unmatched_count,
            "underpayments_detected": underpayments_detected,
            "underpayment_count": underpayment_count,
            "denials_routed": denials_routed,
            "denials_amount": denials_amount,
            "auto_post_rate": auto_post_rate,
        }

    # ── Unmatched Lines ────────────────────────────────────────────────

    async def list_unmatched(
        self,
        db: AsyncSession,
        practice_id: UUID,
        payer_id: UUID | None = None,
        min_amount: float | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[PaymentLine]:
        """List all unmatched payment lines across batches for resolution."""
        query = select(PaymentLine).where(
            PaymentLine.practice_id == practice_id,
            PaymentLine.match_status.in_(["unmatched", "partial", "exception"]),
        )
        if payer_id:
            # Join through PaymentBatch to filter by payer
            query = query.join(PaymentBatch, PaymentLine.batch_id == PaymentBatch.id).where(
                PaymentBatch.payer_id == payer_id
            )
        if min_amount is not None:
            query = query.where(PaymentLine.paid_amount >= min_amount)
        query = query.order_by(PaymentLine.created_at).offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        return list(result.scalars().all())

    # ── Helper Methods ─────────────────────────────────────────────────

    async def _get_batch_or_raise(
        self, db: AsyncSession, batch_id: UUID, practice_id: UUID
    ) -> PaymentBatch:
        """Load a payment batch with tenant isolation check."""
        result = await db.execute(
            select(PaymentBatch).where(
                PaymentBatch.id == batch_id,
                PaymentBatch.practice_id == practice_id,
            )
        )
        batch = result.scalar_one_or_none()
        if not batch:
            raise BatchNotFoundError(batch_id)
        return batch

    async def _get_line_or_raise(
        self, db: AsyncSession, line_id: UUID, practice_id: UUID
    ) -> PaymentLine:
        """Load a payment line with tenant isolation check."""
        result = await db.execute(
            select(PaymentLine).where(
                PaymentLine.id == line_id,
                PaymentLine.practice_id == practice_id,
            )
        )
        line = result.scalar_one_or_none()
        if not line:
            raise PaymentLineNotFoundError(line_id)
        return line

    async def _resolve_payer(
        self, db: AsyncSession, payer_id_number: str, payer_name: str
    ) -> Payer:
        """Look up Payer by payer_id_number, create placeholder if not found."""
        result = await db.execute(
            select(Payer).where(Payer.payer_id_number == payer_id_number)
        )
        payer = result.scalar_one_or_none()
        if payer:
            return payer
        # Create placeholder payer
        payer = Payer(
            payer_name=payer_name or f"Unknown Payer ({payer_id_number})",
            payer_id_number=payer_id_number,
            payer_type="commercial",
            is_active=True,
        )
        db.add(payer)
        await db.flush()
        logger.info("payer_created", payer_id=str(payer.id), payer_id_number=payer_id_number)
        return payer

    def _map_payment_method(self, method: str) -> str:
        """Map ERA payment method codes to our enum values."""
        mapping = {"CHK": "check", "ACH": "eft", "FWT": "eft", "NON": "check", "BOP": "check"}
        return mapping.get(method.upper(), "check")

    async def _match_payment_line_to_claim(
        self,
        db: AsyncSession,
        practice_id: UUID,
        payer_id: UUID,
        claim_number: str,
        total_charge: float,
        patient_name: str,
    ) -> tuple[Claim | None, float]:
        """Attempt to match a payment line to an existing Claim.

        Returns (claim, confidence) tuple. confidence is 0.0 if no match.
        """
        # Step 1: Exact match on claim_number
        result = await db.execute(
            select(Claim).where(
                Claim.claim_number == claim_number,
                Claim.practice_id == practice_id,
            )
        )
        claim = result.scalar_one_or_none()
        if claim:
            return claim, 1.0

        # Step 2: Fallback on clearinghouse_ref
        result = await db.execute(
            select(Claim).where(
                Claim.clearinghouse_ref == claim_number,
                Claim.practice_id == practice_id,
            )
        )
        claim = result.scalar_one_or_none()
        if claim:
            return claim, 0.85

        # Step 3: No match
        return None, 0.0

    async def _detect_underpayment(
        self,
        db: AsyncSession,
        practice_id: UUID,
        payer_id: UUID,
        payment_line: PaymentLine,
        service_line,  # EDIServiceLine
    ) -> tuple[bool, float]:
        """Detect if a payment line is underpaid compared to the fee schedule rate.

        Returns (is_underpaid, underpayment_amount).
        """
        fee_rate = await self._lookup_fee_schedule_rate(
            db, practice_id, payer_id,
            payment_line.cpt_code,
            service_line.modifiers[0] if service_line.modifiers else None,
            None,  # place_of_service not available on payment line
            service_line.service_date_from,
        )
        if fee_rate is None:
            # No fee schedule rate found — cannot determine underpayment
            return False, 0.0

        expected_allowed = float(fee_rate.allowed_amount)
        actual_paid = payment_line.paid_amount
        tolerance_threshold = expected_allowed * (1 - UNDERPAYMENT_TOLERANCE)

        if actual_paid < tolerance_threshold:
            underpayment_amount = expected_allowed - actual_paid
            return True, underpayment_amount

        return False, 0.0

    async def _lookup_fee_schedule_rate(
        self,
        db: AsyncSession,
        practice_id: UUID,
        payer_id: UUID,
        cpt_code: str | None,
        modifier: str | None,
        place_of_service: str | None,
        service_date: date | None,
    ) -> FeeScheduleRate | None:
        """Look up the fee schedule rate for a CPT code under the payer's fee schedule."""
        if not cpt_code:
            return None

        # Get PayerEnrollment to find fee_schedule_id
        enrollment_result = await db.execute(
            select(PayerEnrollment).where(
                PayerEnrollment.practice_id == practice_id,
                PayerEnrollment.payer_id == payer_id,
                PayerEnrollment.is_active == True,
            )
        )
        enrollment = enrollment_result.scalar_one_or_none()
        if not enrollment or not enrollment.fee_schedule_id:
            return None

        # Query for the rate
        query = select(FeeScheduleRate).where(
            FeeScheduleRate.fee_schedule_id == enrollment.fee_schedule_id,
            FeeScheduleRate.cpt_code == cpt_code,
        )
        if modifier:
            query = query.where(
                or_(FeeScheduleRate.modifier == modifier, FeeScheduleRate.modifier.is_(None))
            )
        else:
            query = query.where(FeeScheduleRate.modifier.is_(None))

        if place_of_service:
            query = query.where(
                or_(FeeScheduleRate.place_of_service == place_of_service, FeeScheduleRate.place_of_service.is_(None))
            )

        if service_date:
            query = query.where(FeeScheduleRate.effective_date <= service_date)

        query = query.order_by(FeeScheduleRate.effective_date.desc())
        result = await db.execute(query)
        return result.scalar_one_or_none()

    async def _auto_post_line(
        self,
        db: AsyncSession,
        claim: Claim,
        payment_line: PaymentLine,
        edi_claim,  # EDIClaim
    ) -> bool:
        """Auto-post a payment line to the matched claim.

        Returns True if posted successfully, False otherwise.
        """
        # Only auto-post if not underpaid and no denials
        if payment_line.is_underpaid:
            return False
        if edi_claim.has_denials:
            return False

        # Update claim financials
        claim.total_paid = (claim.total_paid or 0) + payment_line.paid_amount

        # Load adjustments for this line
        adj_result = await db.execute(
            select(Adjustment).where(Adjustment.payment_line_id == payment_line.id)
        )
        adjustments = list(adj_result.scalars().all())
        contractual = sum(a.amount for a in adjustments if a.group_code == "CO")
        patient_resp = sum(a.amount for a in adjustments if a.group_code == "PR")
        claim.total_adjusted = (claim.total_adjusted or 0) + contractual
        claim.patient_responsibility = (claim.patient_responsibility or 0) + patient_resp

        # Update claim status
        if claim.total_paid >= claim.total_charge:
            claim.status = "paid"
        else:
            claim.status = "partial_paid"

        # Update claim line amounts
        if payment_line.claim_line_id:
            cl_result = await db.execute(
                select(ClaimLine).where(ClaimLine.id == payment_line.claim_line_id)
            )
            claim_line = cl_result.scalar_one_or_none()
            if claim_line:
                claim_line.paid_amount = payment_line.paid_amount
                if payment_line.allowed_amount:
                    claim_line.allowed_amount = payment_line.allowed_amount

        # Set claim adjudication date
        claim.adjudication_date = datetime.now(timezone.utc)

        payment_line.match_status = "matched"
        await db.flush()

        logger.info(
            "auto_posted",
            claim_id=str(claim.id),
            line_id=str(payment_line.id),
            paid=payment_line.paid_amount,
        )
        return True

    async def _route_denials(
        self,
        db: AsyncSession,
        practice_id: UUID,
        payer_id: UUID,
        claim: Claim,
        payment_line: PaymentLine,
        edi_claim,  # EDIClaim
    ) -> list[Denial]:
        """Create Denial records for denial adjustments and update claim status."""
        denials = []

        # Collect all denial adjustments
        all_adjustments = list(edi_claim.claim_adjustments)
        for svc_line in edi_claim.service_lines:
            all_adjustments.extend(svc_line.adjustments)

        denial_adjustments = [adj for adj in all_adjustments if adj.is_denial]

        for adj in denial_adjustments:
            denial = Denial(
                practice_id=practice_id,
                claim_id=claim.id,
                payer_id=payer_id,
                denial_date=edi_claim.service_date_from or date.today(),
                reason_code=adj.reason_code,
                remark_codes=adj.remark_codes,
                denial_amount=float(adj.amount),
                status="new",
                priority_score=70.0,
            )
            db.add(denial)
            denials.append(denial)

        await db.flush()

        # Update claim status to denied if currently in a matchable status
        if claim.status in ("submitted", "accepted", "paid", "partial_paid"):
            claim.status = "denied"

        # Create work queue items for denials
        for denial in denials:
            wqi = WorkQueueItem(
                practice_id=practice_id,
                queue_type="denial",
                item_type="denial",
                item_id=denial.id,
                priority=70,
            )
            db.add(wqi)

        await db.flush()
        logger.info("denials_routed", claim_id=str(claim.id), denial_count=len(denials))
        return denials


# Module-level singleton
payment_service = PaymentService()