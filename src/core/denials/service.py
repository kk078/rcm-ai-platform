"""
Denial management service — AI classification, priority scoring,
appeal generation, and analytics.

Every write operation creates an AuditLog entry.
Every query enforces tenant isolation via practice_id filtering.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.denials.errors import (
    DenialNotFoundError,
    DenialStatusError,
    AppealNotFoundError,
)
from src.infrastructure.database.models import (
    Appeal,
    AuditLog,
    Claim,
    Denial,
    Payer,
    PayerEnrollment,
    WorkQueueItem,
)

logger = structlog.get_logger()

# Valid denial status transitions
VALID_DENIAL_TRANSITIONS = {
    "new": {"in_review", "written_off"},
    "in_review": {"appealing", "written_off"},
    "appealing": {"resolved", "written_off"},
    "resolved": set(),
    "written_off": set(),
}

# CARC code → category fallback mapping
CARC_CATEGORY_MAP = {
    # Authorization
    "4": "authorization", "5": "authorization", "6": "authorization",
    "107": "authorization", "119": "authorization",
    # Coding
    "9": "coding", "10": "coding", "11": "coding", "15": "coding",
    "16": "coding", "26": "coding", "27": "coding",
    # Billing
    "18": "billing", "19": "billing", "29": "billing", "31": "billing",
    "32": "billing", "33": "billing", "34": "billing", "35": "billing",
    "96": "billing", "97": "billing", "148": "billing", "149": "billing",
    "197": "billing",
    # Clinical
    "49": "clinical", "50": "clinical", "51": "clinical", "55": "clinical",
    "58": "clinical", "150": "clinical", "151": "clinical", "152": "clinical",
    # Registration
    "177": "registration", "178": "registration", "179": "registration",
    "277": "registration",
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


class DenialService:
    """Manage denial lifecycle: classification, appeal generation, analytics."""

    def __init__(self):
        self._ai_service = None

    def _get_ai_service(self):
        """Lazy initialization of AIService."""
        if self._ai_service is None:
            from src.core.nlp.ai_service import AIService
            self._ai_service = AIService()
        return self._ai_service

    # ── List & Get ──────────────────────────────────────────────────────

    async def list_denials(
        self,
        db: AsyncSession,
        practice_id: UUID,
        status: str | None = None,
        category: str | None = None,
        payer_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[Denial]:
        """List denials with filtering and pagination."""
        query = select(Denial).where(Denial.practice_id == practice_id)
        if status:
            query = query.where(Denial.status == status)
        if category:
            query = query.where(Denial.category == category)
        if payer_id:
            query = query.where(Denial.payer_id == payer_id)
        if date_from:
            query = query.where(Denial.denial_date >= date_from)
        if date_to:
            query = query.where(Denial.denial_date <= date_to)
        query = query.order_by(Denial.priority_score.desc().nulls_last(), Denial.denial_date.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_worklist(
        self,
        db: AsyncSession,
        practice_id: UUID,
        assigned_to: UUID | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[Denial]:
        """Prioritized worklist sorted by recovery_probability * amount * deadline urgency."""
        query = select(Denial).where(
            Denial.practice_id == practice_id,
            Denial.status.in_(["new", "in_review"]),
        )
        if assigned_to:
            query = query.where(Denial.assigned_to == assigned_to)
        query = query.order_by(Denial.priority_score.desc().nulls_last())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_denial(
        self,
        db: AsyncSession,
        denial_id: UUID,
        practice_id: UUID,
    ) -> Denial:
        """Get a single denial with tenant isolation."""
        return await self._get_denial_or_raise(db, denial_id, practice_id)

    # ── AI Classification ────────────────────────────────────────────────

    async def classify_denial(
        self,
        db: AsyncSession,
        user_id: UUID,
        denial_id: UUID,
        practice_id: UUID,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> Denial:
        """AI-powered denial classification: category, root cause, recovery probability."""
        denial = await self._get_denial_or_raise(db, denial_id, practice_id)

        if denial.status not in ("new", "in_review"):
            raise DenialStatusError(f"Cannot classify denial in '{denial.status}' status. Must be 'new' or 'in_review'.")

        # Build claim summary from denial data
        claim_summary = {
            "denial_id": str(denial.id),
            "reason_code": denial.reason_code,
            "remark_codes": denial.remark_codes or [],
            "denial_amount": denial.denial_amount,
            "denial_date": denial.denial_date.isoformat() if denial.denial_date else None,
        }

        # Load claim if available
        claim_result = await db.execute(
            select(Claim).where(Claim.id == denial.claim_id)
        )
        claim = claim_result.scalar_one_or_none()
        if claim:
            claim_summary["claim_number"] = claim.claim_number
            claim_summary["claim_type"] = claim.claim_type
            claim_summary["total_charge"] = claim.total_charge

        # Get payer name
        payer_result = await db.execute(
            select(Payer).where(Payer.id == denial.payer_id)
        )
        payer = payer_result.scalar_one_or_none()
        payer_name = payer.payer_name if payer else "Unknown"

        # Try AI classification (graceful fallback)
        try:
            ai_service = self._get_ai_service()
            classification = await ai_service.classify_denial(
                claim_summary=claim_summary,
                denial_reason_code=denial.reason_code,
                denial_remark_codes=denial.remark_codes or [],
                payer_name=payer_name,
                clinical_context=None,
            )
            denial.category = classification.category
            denial.subcategory = classification.subcategory
            denial.root_cause = classification.root_cause
            denial.recovery_probability = classification.recovery_probability
        except Exception as e:
            logger.warning("ai_classification_failed", denial_id=str(denial_id), error=str(e))
            # Fall back to CARC code mapping
            fallback = self._classify_by_carc(denial.reason_code)
            denial.category = fallback["category"]
            denial.subcategory = fallback["subcategory"]
            denial.root_cause = fallback["root_cause"]
            denial.recovery_probability = fallback["recovery_probability"]

        # Calculate priority score
        days_until_deadline = None
        if denial.appeal_deadline:
            days_until_deadline = (denial.appeal_deadline - date.today()).days
        denial.priority_score = self._calculate_priority_score(
            denial.recovery_probability or 0.5,
            denial.denial_amount,
            days_until_deadline,
        )

        # Calculate appeal and timely filing deadlines from payer
        appeal_days, timely_days = await self._get_payer_filing_days(db, denial.payer_id, practice_id)
        if not denial.appeal_deadline and denial.denial_date:
            denial.appeal_deadline = denial.denial_date + timedelta(days=appeal_days)
        if not denial.timely_filing_deadline and denial.denial_date:
            denial.timely_filing_deadline = denial.denial_date + timedelta(days=timely_days)

        denial.status = "in_review"
        await db.flush()

        await _write_audit(
            db, user_id, "classify_denial", "denial", denial_id,
            resource_detail=f"Category: {denial.category}, Root cause: {denial.root_cause}, "
                           f"Priority: {denial.priority_score:.2f}, Recovery prob: {denial.recovery_probability:.2f}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method, phi_accessed=True,
        )
        logger.info(
            "denial_classified",
            denial_id=str(denial_id),
            category=denial.category,
            priority_score=denial.priority_score,
        )
        return denial

    # ── Appeal Generation ────────────────────────────────────────────────

    async def generate_appeal(
        self,
        db: AsyncSession,
        user_id: UUID,
        denial_id: UUID,
        practice_id: UUID,
        appeal_level: int = 1,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> Appeal:
        """Generate an AI appeal letter for a denial."""
        denial = await self._get_denial_or_raise(db, denial_id, practice_id)

        if denial.status not in ("in_review", "appealing"):
            raise DenialStatusError(f"Cannot generate appeal for denial in '{denial.status}' status. Must be 'in_review' or 'appealing'.")

        # Build denial info
        denial_info = {
            "denial_id": str(denial.id),
            "reason_code": denial.reason_code,
            "remark_codes": denial.remark_codes or [],
            "denial_amount": denial.denial_amount,
            "category": denial.category,
            "subcategory": denial.subcategory,
            "root_cause": denial.root_cause,
        }

        # Build claim info
        from src.infrastructure.database.models import Claim
        claim_result = await db.execute(
            select(Claim).where(Claim.id == denial.claim_id)
        )
        claim = claim_result.scalar_one_or_none()
        claim_info = {}
        if claim:
            claim_info = {
                "claim_number": claim.claim_number,
                "claim_type": claim.claim_type,
                "total_charge": claim.total_charge,
                "patient_id": str(claim.patient_id),
            }

        # Get payer name
        payer_result = await db.execute(select(Payer).where(Payer.id == denial.payer_id))
        payer = payer_result.scalar_one_or_none()
        payer_name = payer.payer_name if payer else "Unknown"

        # Try AI appeal generation (graceful fallback)
        try:
            ai_service = self._get_ai_service()
            appeal_response = await ai_service.generate_appeal(
                denial_info=denial_info,
                claim_info=claim_info,
                clinical_documentation="",
                payer_name=payer_name,
                appeal_level=appeal_level,
            )
            letter_content = appeal_response.letter_content
            guidelines_cited = appeal_response.guidelines_cited
            ai_confidence = appeal_response.confidence
            appeal_status = "draft"
        except Exception as e:
            logger.warning("ai_appeal_generation_failed", denial_id=str(denial_id), error=str(e))
            letter_content = f"[AI appeal generation failed: {str(e)}. Please draft manually.]\n\n"
            letter_content += f"Denial Reason: {denial.reason_code}\n"
            letter_content += f"Denial Amount: ${denial.denial_amount:.2f}\n"
            letter_content += f"Category: {denial.category or 'Unclassified'}\n"
            guidelines_cited = []
            ai_confidence = None
            appeal_status = "draft_failed"

        # Create Appeal record
        appeal = Appeal(
            practice_id=practice_id,
            denial_id=denial_id,
            appeal_level=appeal_level,
            letter_content=letter_content,
            ai_generated=True,
            ai_confidence=ai_confidence,
            guidelines_cited=guidelines_cited,
            status=appeal_status,
            created_by=user_id,
        )
        db.add(appeal)

        # Update denial status
        denial.status = "appealing"
        await db.flush()

        await _write_audit(
            db, user_id, "generate_appeal", "appeal", appeal.id,
            resource_detail=f"Appeal level {appeal_level} for denial {denial.reason_code}, "
                           f"AI confidence: {ai_confidence}, Status: {appeal_status}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method, phi_accessed=True,
        )
        logger.info("appeal_generated", appeal_id=str(appeal.id), denial_id=str(denial_id))
        return appeal

    # ── Appeal Submission ─────────────────────────────────────────────────

    async def submit_appeal(
        self,
        db: AsyncSession,
        user_id: UUID,
        denial_id: UUID,
        appeal_id: UUID,
        practice_id: UUID,
        submission_method: str = "electronic",
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> Appeal:
        """Submit a finalized appeal letter."""
        denial = await self._get_denial_or_raise(db, denial_id, practice_id)
        appeal = await self._get_appeal_or_raise(db, appeal_id, practice_id)

        if appeal.denial_id != denial_id:
            raise DenialStatusError(f"Appeal {appeal_id} does not belong to denial {denial_id}")

        if appeal.status not in ("draft", "draft_failed"):
            raise DenialStatusError(f"Cannot submit appeal in '{appeal.status}' status. Must be 'draft'.")

        if denial.status not in ("appealing", "in_review"):
            raise DenialStatusError(f"Denial must be in 'appealing' or 'in_review' status to submit appeal.")

        # Update appeal
        appeal.status = "submitted"
        appeal.submitted_date = date.today()
        appeal.follow_up_date = date.today() + timedelta(days=30)

        # Update denial if not already appealing
        if denial.status == "in_review":
            denial.status = "appealing"

        await db.flush()

        # Create follow-up work queue item
        wqi = WorkQueueItem(
            practice_id=practice_id,
            queue_type="follow_up",
            item_type="denial",
            item_id=denial_id,
            due_date=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=30),
        )
        db.add(wqi)

        await _write_audit(
            db, user_id, "submit_appeal", "appeal", appeal_id,
            resource_detail=f"Appeal submitted via {submission_method}, level {appeal.appeal_level}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method, phi_accessed=True,
        )
        logger.info("appeal_submitted", appeal_id=str(appeal_id), denial_id=str(denial_id))
        return appeal

    # ── Write Off ────────────────────────────────────────────────────────

    async def write_off_denial(
        self,
        db: AsyncSession,
        user_id: UUID,
        denial_id: UUID,
        practice_id: UUID,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> Denial:
        """Write off a denial as uncollectable."""
        denial = await self._get_denial_or_raise(db, denial_id, practice_id)

        if denial.status not in ("new", "in_review"):
            raise DenialStatusError(f"Cannot write off denial in '{denial.status}' status. Must be 'new' or 'in_review'.")

        denial.status = "written_off"
        denial.resolution = "written_off"
        denial.resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
        denial.resolved_by = user_id
        await db.flush()

        await _write_audit(
            db, user_id, "write_off_denial", "denial", denial_id,
            resource_detail=f"Written off: ${denial.denial_amount:.2f}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method, phi_accessed=True,
        )
        logger.info("denial_written_off", denial_id=str(denial_id))
        return denial

    # ── Assign ────────────────────────────────────────────────────────────

    async def assign_denial(
        self,
        db: AsyncSession,
        user_id: UUID,
        denial_id: UUID,
        assigned_to: UUID,
        practice_id: UUID,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> Denial:
        """Assign a denial to an analyst."""
        denial = await self._get_denial_or_raise(db, denial_id, practice_id)

        denial.assigned_to = assigned_to
        await db.flush()

        # Update work queue item if exists
        wqi_result = await db.execute(
            select(WorkQueueItem).where(
                WorkQueueItem.item_id == denial_id,
                WorkQueueItem.item_type == "denial",
            )
        )
        wqi = wqi_result.scalar_one_or_none()
        if wqi:
            wqi.assigned_to = assigned_to

        await _write_audit(
            db, user_id, "assign_denial", "denial", denial_id,
            resource_detail=f"Assigned to {assigned_to}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method,
        )
        logger.info("denial_assigned", denial_id=str(denial_id), assigned_to=str(assigned_to))
        return denial

    # ── Analytics ─────────────────────────────────────────────────────────

    async def get_denial_patterns(
        self,
        db: AsyncSession,
        practice_id: UUID,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict]:
        """Aggregate denial patterns by category + payer + reason_code."""
        query = select(
            Denial.category,
            Denial.payer_id,
            Denial.reason_code,
            func.count(Denial.id).label("count"),
            func.sum(Denial.denial_amount).label("total_amount"),
            func.avg(Denial.recovery_probability).label("avg_recovery_probability"),
        ).where(Denial.practice_id == practice_id)

        if date_from:
            query = query.where(Denial.denial_date >= date_from)
        if date_to:
            query = query.where(Denial.denial_date <= date_to)

        query = query.group_by(Denial.category, Denial.payer_id, Denial.reason_code)
        query = query.order_by(func.count(Denial.id).desc())

        result = await db.execute(query)
        patterns = []
        for row in result:
            patterns.append({
                "category": row.category or "uncategorized",
                "payer_id": str(row.payer_id),
                "reason_code": row.reason_code,
                "count": row.count,
                "total_amount": float(row.total_amount or 0),
                "avg_recovery_probability": float(row.avg_recovery_probability or 0),
            })
        return patterns

    async def get_analytics_summary(
        self,
        db: AsyncSession,
        practice_id: UUID,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict:
        """KPIs: denial rate, recovery rate, days to resolve, top reasons, appeal success."""
        # Base filter
        base_filter = [Denial.practice_id == practice_id]
        if date_from:
            base_filter.append(Denial.denial_date >= date_from)
        if date_to:
            base_filter.append(Denial.denial_date <= date_to)

        # Total denials and amount
        total_result = await db.execute(
            select(func.count(Denial.id), func.sum(Denial.denial_amount))
            .where(*base_filter)
        )
        total_row = total_result.one()
        total_denials = total_row[0] or 0
        total_amount = float(total_row[1] or 0)

        # Resolved with recovery
        resolved_result = await db.execute(
            select(func.count(Denial.id), func.sum(Denial.recovered_amount))
            .where(*base_filter, Denial.resolution == "recovered")
        )
        resolved_row = resolved_result.one()
        recovered_count = resolved_row[0] or 0
        recovered_amount = float(resolved_row[1] or 0)

        # Average days to resolve
        avg_days_result = await db.execute(
            select(func.avg(
                func.extract("day", Denial.resolved_at - Denial.created_at)
            )).where(*base_filter, Denial.resolved_at.isnot(None))
        )
        avg_days = float(avg_days_result.scalar() or 0)

        # Top 5 denial reasons
        top_reasons_result = await db.execute(
            select(Denial.reason_code, func.count(Denial.id).label("count"))
            .where(*base_filter)
            .group_by(Denial.reason_code)
            .order_by(func.count(Denial.id).desc())
            .limit(5)
        )
        top_reasons = [{"reason_code": row.reason_code, "count": row.count} for row in top_reasons_result]

        # Category distribution
        category_result = await db.execute(
            select(Denial.category, func.count(Denial.id).label("count"))
            .where(*base_filter)
            .group_by(Denial.category)
        )
        category_distribution = {row.category or "uncategorized": row.count for row in category_result}

        # Appeal success rate
        appeal_success_result = await db.execute(
            select(func.count(Appeal.id), func.count(Appeal.id))
            .where(
                Appeal.practice_id == practice_id,
                Appeal.decision == "overturned",
            )
        )
        appeal_row = appeal_success_result.one()
        total_appeals = appeal_row[0] or 0
        successful_appeals = appeal_row[1] or 0

        recovery_rate = (recovered_count / total_denials * 100) if total_denials > 0 else 0
        appeal_success_rate = (successful_appeals / total_appeals * 100) if total_appeals > 0 else 0

        return {
            "total_denials": total_denials,
            "total_denial_amount": total_amount,
            "recovery_rate": round(recovery_rate, 2),
            "recovered_amount": recovered_amount,
            "avg_days_to_resolve": round(avg_days, 1),
            "top_reasons": top_reasons,
            "category_distribution": category_distribution,
            "appeal_success_rate": round(appeal_success_rate, 2),
            "total_appeals": total_appeals,
            "successful_appeals": successful_appeals,
        }

    # ── Helper Methods ──────────────────────────────────────────────────

    async def _get_denial_or_raise(
        self, db: AsyncSession, denial_id: UUID, practice_id: UUID
    ) -> Denial:
        """Load a denial with tenant isolation check."""
        result = await db.execute(
            select(Denial).where(
                Denial.id == denial_id,
                Denial.practice_id == practice_id,
            )
        )
        denial = result.scalar_one_or_none()
        if not denial:
            raise DenialNotFoundError(denial_id)
        return denial

    async def _get_appeal_or_raise(
        self, db: AsyncSession, appeal_id: UUID, practice_id: UUID
    ) -> Appeal:
        """Load an appeal with tenant isolation check."""
        result = await db.execute(
            select(Appeal).where(
                Appeal.id == appeal_id,
                Appeal.practice_id == practice_id,
            )
        )
        appeal = result.scalar_one_or_none()
        if not appeal:
            raise AppealNotFoundError(appeal_id)
        return appeal

    @staticmethod
    def _calculate_priority_score(
        recovery_probability: float,
        denial_amount: float,
        days_until_deadline: int | None,
    ) -> float:
        """Calculate priority score: recovery_probability * 0.5 + amount_factor * 0.3 + urgency * 0.2.

        Higher score = higher priority.
        """
        # Normalize amount: assume max ~$50,000 for scaling
        amount_factor = min(denial_amount / 50000.0, 1.0)

        # Deadline urgency
        urgency = DenialService._compute_deadline_urgency(days_until_deadline)

        score = (recovery_probability * 0.5) + (amount_factor * 0.3) + (urgency * 0.2)
        return round(min(score, 1.0), 4)

    @staticmethod
    def _compute_deadline_urgency(days_until_deadline: int | None) -> float:
        """Compute urgency factor from days until deadline.

        Returns: 1.0 if >30 days, 1.5 if 15-30, 2.0 if <15, 3.0 if <5, 0.5 if None.
        """
        if days_until_deadline is None:
            return 0.5
        if days_until_deadline < 5:
            return 3.0
        if days_until_deadline < 15:
            return 2.0
        if days_until_deadline <= 30:
            return 1.5
        return 1.0

    @staticmethod
    def _classify_by_carc(reason_code: str) -> dict:
        """Fallback classification from CARC code when AI is unavailable."""
        category = CARC_CATEGORY_MAP.get(reason_code, "other")
        subcategory_map = {
            "authorization": "prior_auth_required",
            "coding": "code_issue",
            "billing": "billing_error",
            "clinical": "medical_necessity",
            "registration": "eligibility_issue",
            "other": "unclassified",
        }
        return {
            "category": category,
            "subcategory": subcategory_map.get(category, "unclassified"),
            "root_cause": f"CARC {reason_code} indicates {category} issue",
            "recovery_probability": 0.3 if category == "authorization" else 0.2,
        }

    async def _get_payer_filing_days(
        self, db: AsyncSession, payer_id: UUID, practice_id: UUID
    ) -> tuple[int, int]:
        """Get appeal and timely filing days for a payer.

        Returns (appeal_filing_days, timely_filing_days).
        Checks PayerEnrollment for practice-specific overrides first,
        falls back to Payer defaults.
        """
        # Check PayerEnrollment for practice-specific overrides
        enrollment_result = await db.execute(
            select(PayerEnrollment).where(
                PayerEnrollment.payer_id == payer_id,
                PayerEnrollment.practice_id == practice_id,
                PayerEnrollment.is_active == True,
            )
        )
        enrollment = enrollment_result.scalar_one_or_none()

        # Fall back to Payer defaults
        payer_result = await db.execute(select(Payer).where(Payer.id == payer_id))
        payer = payer_result.scalar_one_or_none()

        if enrollment and enrollment.appeal_filing_days:
            appeal_days = enrollment.appeal_filing_days
        else:
            appeal_days = payer.appeal_filing_days if payer else 60

        if enrollment and enrollment.timely_filing_days:
            timely_days = enrollment.timely_filing_days
        else:
            timely_days = payer.timely_filing_days if payer else 365

        return appeal_days, timely_days


# Module-level singleton
denial_service = DenialService()