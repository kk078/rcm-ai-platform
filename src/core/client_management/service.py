"""
Client management service layer — Practice onboarding, staff assignments,
portal users, and all related business logic.

Every write operation creates an AuditLog entry.
Every query enforces tenant isolation via practice_id filtering.
"""

from __future__ import annotations

import secrets
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.client_management.errors import (
    InvalidFeeModelError,
    OnboardingIncompleteError,
    PayerEnrollmentConflictError,
    PayerNotFoundError,
    PracticeAlreadyExistsError,
    PracticeNotFoundError,
    PracticeStatusError,
    ServiceAgreementConflictError,
    ServiceAgreementNotFoundError,
    StaffAssignmentConflictError,
    StaffAssignmentNotFoundError,
    UserAlreadyExistsError,
    UserNotFoundError,
)
from src.infrastructure.auth.service import AuthService
from src.infrastructure.database.models import (
    AuditLog,
    Payer,
    PayerEnrollment,
    Practice,
    PracticeLocation,
    Provider,
    ServiceAgreement,
    StaffAssignment,
    User,
)

logger = structlog.get_logger()

# Allowed fields for practice updates (exclude id, status, created_by, timestamps)
PRACTICE_UPDATABLE_FIELDS = {
    "practice_name", "legal_name", "group_npi", "specialty_primary",
    "specialty_codes", "address_line_1", "address_line_2", "city", "state",
    "zip_code", "phone", "fax", "email", "website", "contact_name",
    "contact_phone", "contact_email", "intake_method", "timezone",
    "default_clearinghouse", "notes",
}

# Allowed fields for payer enrollment updates
ENROLLMENT_UPDATABLE_FIELDS = {
    "group_number", "edi_payer_id", "era_enrolled", "era_enrollment_date",
    "eft_enrolled", "eft_enrollment_date", "clearinghouse", "sender_id",
    "receiver_id", "timely_filing_days", "appeal_filing_days",
    "appeal_address", "appeal_fax", "payer_portal_url", "payer_portal_login",
    "payer_phone", "payer_rep_name", "fee_schedule_id", "is_active",
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


class PracticeService:
    """CRUD + lifecycle management for Practice entities."""

    async def create_practice(
        self,
        db: AsyncSession,
        user_id: UUID,
        data,  # PracticeCreate Pydantic model
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> Practice:
        practice = Practice(
            practice_name=data.practice_name,
            legal_name=data.legal_name,
            tin=data.tin,
            group_npi=data.group_npi,
            specialty_primary=data.specialty_primary,
            address_line_1=data.address_line_1,
            city=data.city,
            state=data.state,
            zip_code=data.zip_code,
            phone=data.phone,
            fax=data.fax,
            email=data.email,
            contact_name=data.contact_name,
            contact_email=data.contact_email,
            intake_method=data.intake_method.value if hasattr(data.intake_method, "value") else data.intake_method,
            timezone=data.timezone,
            status="onboarding",
            created_by=user_id,
        )
        db.add(practice)
        await db.flush()

        await _write_audit(
            db, user_id, "create_practice", "practice", practice.id,
            ip_address=ip_address, request_path=request_path,
            request_method=request_method, phi_accessed=True,  # TIN is PHI
        )
        logger.info("practice_created", practice_id=str(practice.id), name=practice.practice_name)
        return practice

    async def get_practice(self, db: AsyncSession, practice_id: UUID) -> Practice:
        result = await db.execute(select(Practice).where(Practice.id == practice_id))
        practice = result.scalar_one_or_none()
        if not practice:
            raise PracticeNotFoundError(practice_id)
        return practice

    async def list_practices(
        self,
        db: AsyncSession,
        status: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[Practice]:
        query = select(Practice)
        if status:
            query = query.where(Practice.status == status)
        if search:
            query = query.where(Practice.practice_name.ilike(f"%{search}%"))
        query = query.order_by(Practice.practice_name).offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        return list(result.scalars().all())

    async def update_practice(
        self,
        db: AsyncSession,
        user_id: UUID,
        practice_id: UUID,
        updates: dict,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> Practice:
        practice = await self.get_practice(db, practice_id)
        for key, value in updates.items():
            if key in PRACTICE_UPDATABLE_FIELDS:
                setattr(practice, key, value)
        await db.flush()

        await _write_audit(
            db, user_id, "update_practice", "practice", practice.id,
            resource_detail=f"Updated fields: {', '.join(k for k in updates if k in PRACTICE_UPDATABLE_FIELDS)}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method, phi_accessed=True,
        )
        return practice

    async def activate_practice(
        self,
        db: AsyncSession,
        user_id: UUID,
        practice_id: UUID,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> Practice:
        practice = await self.get_practice(db, practice_id)
        if practice.status != "onboarding":
            raise PracticeStatusError(f"Cannot activate practice in '{practice.status}' status. Must be 'onboarding'.")

        # Validate onboarding is complete
        onboarding_svc = OnboardingService()
        checklist = await onboarding_svc.get_onboarding_status(db, practice_id)
        missing = [k for k, v in checklist.model_dump().items() if not v and k != "initial_data_migrated"]
        if missing:
            raise OnboardingIncompleteError(
                f"Cannot activate practice. Incomplete: {', '.join(missing)}"
            )

        practice.status = "active"
        practice.go_live_date = date.today()
        practice.onboarded_at = datetime.now(timezone.utc)
        await db.flush()

        await _write_audit(
            db, user_id, "activate_practice", "practice", practice.id,
            ip_address=ip_address, request_path=request_path,
            request_method=request_method,
        )
        logger.info("practice_activated", practice_id=str(practice.id))
        return practice

    async def suspend_practice(
        self,
        db: AsyncSession,
        user_id: UUID,
        practice_id: UUID,
        reason: str,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> Practice:
        practice = await self.get_practice(db, practice_id)
        if practice.status not in ("active", "onboarding"):
            raise PracticeStatusError(f"Cannot suspend practice in '{practice.status}' status.")
        practice.status = "suspended"
        await db.flush()

        await _write_audit(
            db, user_id, "suspend_practice", "practice", practice.id,
            resource_detail=reason, ip_address=ip_address,
            request_path=request_path, request_method=request_method,
        )
        return practice

    async def terminate_practice(
        self,
        db: AsyncSession,
        user_id: UUID,
        practice_id: UUID,
        reason: str,
        effective_date: date,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> Practice:
        practice = await self.get_practice(db, practice_id)
        practice.status = "terminated"
        practice.terminated_at = datetime.now(timezone.utc)
        practice.termination_reason = reason

        # Deactivate all portal users for this practice
        result = await db.execute(
            select(User).where(User.practice_id == practice_id, User.user_type == "provider")
        )
        portal_users = result.scalars().all()
        for user in portal_users:
            user.is_active = False

        await db.flush()

        await _write_audit(
            db, user_id, "terminate_practice", "practice", practice.id,
            resource_detail=f"Reason: {reason}. Effective: {effective_date}. "
                           f"Deactivated {len(portal_users)} portal users.",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method,
        )
        logger.info("practice_terminated", practice_id=str(practice_id), reason=reason)
        return practice


class ProviderService:
    """Manage providers associated with practices."""

    async def add_provider_to_practice(
        self,
        db: AsyncSession,
        user_id: UUID,
        practice_id: UUID,
        data,  # ProviderAdd Pydantic model
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> Provider:
        # Check if provider with this NPI already exists
        result = await db.execute(select(Provider).where(Provider.npi == data.npi))
        provider = result.scalar_one_or_none()

        if provider:
            # Update name/fields if provided
            provider.first_name = data.first_name
            provider.last_name = data.last_name
            if data.credential:
                provider.credential = data.credential
            if data.taxonomy_code:
                provider.taxonomy_code = data.taxonomy_code
            if data.specialty:
                provider.specialty = data.specialty
            await db.flush()
            logger.info("provider_linked", npi=data.npi, practice_id=str(practice_id))
        else:
            # Create new provider
            provider = Provider(
                npi=data.npi,
                first_name=data.first_name,
                last_name=data.last_name,
                credential=data.credential,
                taxonomy_code=data.taxonomy_code,
                specialty=data.specialty,
                is_individual=True,
                is_active=True,
            )
            db.add(provider)
            await db.flush()
            logger.info("provider_created", npi=data.npi, provider_id=str(provider.id))

        await _write_audit(
            db, user_id, "add_provider", "provider", provider.id,
            resource_detail=f"NPI: {data.npi}, Practice: {practice_id}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method,
        )
        return provider

    async def list_practice_providers(
        self, db: AsyncSession, practice_id: UUID
    ) -> list[Provider]:
        # Find providers through portal users linked to this practice
        result = await db.execute(
            select(Provider)
            .join(User, User.provider_id == Provider.id)
            .where(User.practice_id == practice_id, User.user_type == "provider", User.is_active == True)
        )
        providers = list(result.scalars().all())

        # Also check if there are providers referenced in encounters
        from src.infrastructure.database.models import Encounter
        result2 = await db.execute(
            select(Provider)
            .join(Encounter, Encounter.provider_id == Provider.id)
            .where(Encounter.practice_id == practice_id)
            .distinct()
        )
        encounter_providers = list(result2.scalars().all())

        # Merge and deduplicate
        seen = {p.id for p in providers}
        for p in encounter_providers:
            if p.id not in seen:
                providers.append(p)
                seen.add(p.id)

        return providers


class PayerEnrollmentService:
    """Manage payer enrollment records for a practice."""

    async def add_payer_enrollment(
        self,
        db: AsyncSession,
        user_id: UUID,
        practice_id: UUID,
        data,  # PayerEnrollmentCreate Pydantic model
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> PayerEnrollment:
        # Verify payer exists
        result = await db.execute(select(Payer).where(Payer.id == data.payer_id))
        if not result.scalar_one_or_none():
            raise PayerNotFoundError(data.payer_id)

        # Check for duplicate enrollment
        result = await db.execute(
            select(PayerEnrollment).where(
                PayerEnrollment.practice_id == practice_id,
                PayerEnrollment.payer_id == data.payer_id,
            )
        )
        if result.scalar_one_or_none():
            raise PayerEnrollmentConflictError(
                f"Payer {data.payer_id} is already enrolled for practice {practice_id}"
            )

        enrollment = PayerEnrollment(
            practice_id=practice_id,
            payer_id=data.payer_id,
            group_number=data.group_number,
            edi_payer_id=data.edi_payer_id,
            era_enrolled=data.era_enrolled,
            eft_enrolled=data.eft_enrolled,
            clearinghouse=data.clearinghouse,
            sender_id=data.sender_id,
            timely_filing_days=data.timely_filing_days,
            appeal_filing_days=data.appeal_filing_days,
            appeal_address=data.appeal_address,
            appeal_fax=data.appeal_fax,
            fee_schedule_id=data.fee_schedule_id,
            is_active=True,
        )
        db.add(enrollment)
        await db.flush()

        await _write_audit(
            db, user_id, "add_payer_enrollment", "payer_enrollment", enrollment.id,
            resource_detail=f"Payer: {data.payer_id}, Practice: {practice_id}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method,
        )
        return enrollment

    async def update_payer_enrollment(
        self,
        db: AsyncSession,
        user_id: UUID,
        practice_id: UUID,
        enrollment_id: UUID,
        updates: dict,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> PayerEnrollment:
        result = await db.execute(
            select(PayerEnrollment).where(PayerEnrollment.id == enrollment_id)
        )
        enrollment = result.scalar_one_or_none()
        if not enrollment:
            raise PayerEnrollmentConflictError(f"Payer enrollment {enrollment_id} not found")

        # Verify tenant isolation
        if enrollment.practice_id != practice_id:
            raise PayerEnrollmentConflictError("Enrollment does not belong to this practice")

        for key, value in updates.items():
            if key in ENROLLMENT_UPDATABLE_FIELDS:
                setattr(enrollment, key, value)
        await db.flush()

        await _write_audit(
            db, user_id, "update_payer_enrollment", "payer_enrollment", enrollment.id,
            resource_detail=f"Updated fields: {', '.join(k for k in updates if k in ENROLLMENT_UPDATABLE_FIELDS)}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method, phi_accessed=True,  # payer_portal_login is PHI
        )
        return enrollment

    async def list_payer_enrollments(
        self, db: AsyncSession, practice_id: UUID
    ) -> list[PayerEnrollment]:
        result = await db.execute(
            select(PayerEnrollment).where(PayerEnrollment.practice_id == practice_id)
        )
        return list(result.scalars().all())


class ServiceAgreementService:
    """Manage service agreements and fee calculations."""

    async def create_agreement(
        self,
        db: AsyncSession,
        user_id: UUID,
        practice_id: UUID,
        data,  # ServiceAgreementCreate Pydantic model
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> ServiceAgreement:
        # Check for existing active agreement
        result = await db.execute(
            select(ServiceAgreement).where(
                ServiceAgreement.practice_id == practice_id,
                ServiceAgreement.is_active == True,
            )
        )
        if result.scalar_one_or_none():
            raise ServiceAgreementConflictError(
                "An active service agreement already exists for this practice"
            )

        # Validate fee model fields
        fee_model = data.fee_model.value if hasattr(data.fee_model, "value") else data.fee_model
        self._validate_fee_model(fee_model, data)

        agreement = ServiceAgreement(
            practice_id=practice_id,
            fee_model=fee_model,
            percentage_rate=data.percentage_rate,
            per_claim_rate=data.per_claim_rate,
            flat_fee_monthly=data.flat_fee_monthly,
            hybrid_base_fee=data.hybrid_base_fee,
            hybrid_threshold=data.hybrid_threshold,
            hybrid_overage_rate=data.hybrid_overage_rate,
            minimum_monthly_fee=data.minimum_monthly_fee,
            includes_coding=data.includes_coding,
            includes_billing=data.includes_billing,
            includes_posting=data.includes_posting,
            includes_denials=data.includes_denials,
            includes_credentialing=data.includes_credentialing,
            includes_eligibility=data.includes_eligibility,
            includes_patient_collections=data.includes_patient_collections,
            includes_reporting=data.includes_reporting,
            sla_clean_claim_rate=data.sla_clean_claim_rate,
            sla_days_to_submit=data.sla_days_to_submit,
            sla_appeal_turnaround=data.sla_appeal_turnaround,
            sla_posting_turnaround=data.sla_posting_turnaround,
            sla_denial_response=data.sla_denial_response,
            effective_date=data.effective_date,
            termination_date=data.termination_date,
            is_active=True,
        )
        db.add(agreement)
        await db.flush()

        await _write_audit(
            db, user_id, "create_service_agreement", "service_agreement", agreement.id,
            resource_detail=f"Fee model: {fee_model}, Practice: {practice_id}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method,
        )
        return agreement

    @staticmethod
    def _validate_fee_model(fee_model: str, data) -> None:
        """Validate that required fee fields are present for the chosen model."""
        if fee_model == "percentage" and not data.percentage_rate:
            raise InvalidFeeModelError("percentage_rate is required for percentage fee model")
        if fee_model == "per_claim" and not data.per_claim_rate:
            raise InvalidFeeModelError("per_claim_rate is required for per_claim fee model")
        if fee_model == "flat_fee" and not data.flat_fee_monthly:
            raise InvalidFeeModelError("flat_fee_monthly is required for flat_fee fee model")
        if fee_model == "hybrid" and not data.hybrid_base_fee:
            raise InvalidFeeModelError("hybrid_base_fee is required for hybrid fee model")

    async def get_active_agreement(self, db: AsyncSession, practice_id: UUID) -> ServiceAgreement:
        result = await db.execute(
            select(ServiceAgreement).where(
                ServiceAgreement.practice_id == practice_id,
                ServiceAgreement.is_active == True,
            )
        )
        agreement = result.scalar_one_or_none()
        if not agreement:
            raise ServiceAgreementNotFoundError(practice_id)
        return agreement

    async def calculate_fee(
        self,
        db: AsyncSession,
        practice_id: UUID,
        total_collections: float,
        total_claims: int = 0,
    ) -> dict:
        agreement = await self.get_active_agreement(db, practice_id)

        if agreement.fee_model == "percentage":
            calculated_fee = total_collections * (agreement.percentage_rate / 100)
        elif agreement.fee_model == "per_claim":
            calculated_fee = total_claims * (agreement.per_claim_rate
) if agreement.per_claim_rate else 0
        elif agreement.fee_model == "flat_fee":
            calculated_fee = agreement.flat_fee_monthly or 0
        elif agreement.fee_model == "hybrid":
            base = agreement.hybrid_base_fee or 0
            overage = max(0, total_collections - (agreement.hybrid_threshold or 0))
            overage_rate = (agreement.hybrid_overage_rate or 0) / 100
            calculated_fee = base + (overage * overage_rate)
        else:
            raise InvalidFeeModelError(f"Unknown fee model: {agreement.fee_model}")

        minimum_applied = False
        if agreement.minimum_monthly_fee and calculated_fee < agreement.minimum_monthly_fee:
            calculated_fee = agreement.minimum_monthly_fee
            minimum_applied = True

        return {
            "fee_model": agreement.fee_model,
            "calculated_fee": round(calculated_fee, 2),
            "minimum_fee_applied": minimum_applied,
            "total_due": round(calculated_fee, 2),
        }


class StaffAssignmentService:
    """Manage staff assignments to practices."""

    async def assign_staff(
        self,
        db: AsyncSession,
        user_id: UUID,
        practice_id: UUID,
        data,  # StaffAssignmentCreate Pydantic model
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> StaffAssignment:
        # Verify user exists and is internal type
        result = await db.execute(select(User).where(User.id == data.user_id))
        target_user = result.scalar_one_or_none()
        if not target_user:
            raise UserNotFoundError(data.user_id)
        if target_user.user_type != "internal":
            raise PracticeStatusError("Cannot assign non-internal staff to a practice")

        # Check for duplicate assignment
        result = await db.execute(
            select(StaffAssignment).where(
                StaffAssignment.user_id == data.user_id,
                StaffAssignment.practice_id == practice_id,
                StaffAssignment.role_in_practice == data.role_in_practice,
            )
        )
        if result.scalar_one_or_none():
            raise StaffAssignmentConflictError(
                f"User {data.user_id} already assigned to practice {practice_id} "
                f"as {data.role_in_practice}"
            )

        assignment = StaffAssignment(
            practice_id=practice_id,
            user_id=data.user_id,
            role_in_practice=data.role_in_practice,
            is_primary=data.is_primary,
            assigned_by=user_id,
        )
        db.add(assignment)
        await db.flush()

        await _write_audit(
            db, user_id, "assign_staff", "staff_assignment", assignment.id,
            resource_detail=f"User: {data.user_id}, Role: {data.role_in_practice}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method,
        )
        return assignment

    async def list_staff_assignments(
        self, db: AsyncSession, practice_id: UUID
    ) -> list[StaffAssignment]:
        result = await db.execute(
            select(StaffAssignment).where(StaffAssignment.practice_id == practice_id)
        )
        return list(result.scalars().all())

    async def remove_assignment(
        self,
        db: AsyncSession,
        user_id: UUID,
        practice_id: UUID,
        assignment_id: UUID,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> None:
        result = await db.execute(
            select(StaffAssignment).where(StaffAssignment.id == assignment_id)
        )
        assignment = result.scalar_one_or_none()
        if not assignment:
            raise StaffAssignmentNotFoundError(assignment_id)
        if assignment.practice_id != practice_id:
            raise StaffAssignmentNotFoundError(assignment_id)

        await db.delete(assignment)
        await db.flush()

        await _write_audit(
            db, user_id, "remove_staff_assignment", "staff_assignment", assignment_id,
            resource_detail=f"Removed user {assignment.user_id} from practice {practice_id}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method,
        )


class PortalUserService:
    """Manage provider portal user accounts."""

    async def create_portal_user(
        self,
        db: AsyncSession,
        user_id: UUID,
        practice_id: UUID,
        data,  # PortalUserCreate Pydantic model
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> User:
        # Check for duplicate email
        result = await db.execute(select(User).where(User.email == data.email))
        if result.scalar_one_or_none():
            raise UserAlreadyExistsError(data.email)

        # Generate temporary password
        temp_password = secrets.token_urlsafe(16)
        password_hash = AuthService.hash_password(temp_password)

        user = User(
            email=data.email,
            password_hash=password_hash,
            first_name=data.first_name,
            last_name=data.last_name,
            user_type="provider",
            practice_id=practice_id,
            provider_role=data.provider_role,
            provider_id=data.provider_id,
            is_active=True,
            mfa_enabled=False,
        )
        db.add(user)
        await db.flush()

        await _write_audit(
            db, user_id, "create_portal_user", "user", user.id,
            resource_detail=f"Email: {data.email}, Practice: {practice_id}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method,
        )
        logger.info("portal_user_created", user_id=str(user.id), email=data.email, practice_id=str(practice_id))
        # Note: In production, trigger a welcome email with password setup link here
        return user

    async def list_portal_users(
        self, db: AsyncSession, practice_id: UUID
    ) -> list[User]:
        result = await db.execute(
            select(User).where(User.practice_id == practice_id, User.user_type == "provider")
        )
        return list(result.scalars().all())

    async def update_portal_user(
        self,
        db: AsyncSession,
        user_id: UUID,
        practice_id: UUID,
        target_user_id: UUID,
        updates: dict,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> User:
        result = await db.execute(select(User).where(User.id == target_user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise UserNotFoundError(target_user_id)
        if user.practice_id != practice_id:
            raise UserNotFoundError(target_user_id)

        allowed_fields = {"first_name", "last_name", "provider_role", "provider_id"}
        for key, value in updates.items():
            if key in allowed_fields:
                setattr(user, key, value)
        await db.flush()

        await _write_audit(
            db, user_id, "update_portal_user", "user", target_user_id,
            ip_address=ip_address, request_path=request_path,
            request_method=request_method,
        )
        return user

    async def deactivate_portal_user(
        self,
        db: AsyncSession,
        caller_user_id: UUID,
        practice_id: UUID,
        target_user_id: UUID,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> User:
        result = await db.execute(select(User).where(User.id == target_user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise UserNotFoundError(target_user_id)
        if user.practice_id != practice_id:
            raise UserNotFoundError(target_user_id)
        if user.user_type != "provider":
            raise PracticeStatusError("Cannot deactivate non-provider users through this endpoint")

        user.is_active = False
        await db.flush()

        await _write_audit(
            db, caller_user_id, "deactivate_portal_user", "user", target_user_id,
            ip_address=ip_address, request_path=request_path,
            request_method=request_method,
        )
        return user


class OnboardingService:
    """Check onboarding completeness for a practice."""

    async def get_onboarding_status(self, db: AsyncSession, practice_id: UUID) -> dict:
        """Check each onboarding step and return a status dict."""
        # Verify practice exists
        practice = await PracticeService().get_practice(db, practice_id)

        # Check providers (through portal users with provider type)
        provider_result = await db.execute(
            select(func.count()).select(User).where(
                User.practice_id == practice_id,
                User.user_type == "provider",
                User.is_active == True,
            )
        )
        providers_count = provider_result.scalar() or 0

        # Check locations
        loc_result = await db.execute(
            select(func.count()).select(PracticeLocation).where(
                PracticeLocation.practice_id == practice_id,
                PracticeLocation.is_active == True,
            )
        )
        locations_count = loc_result.scalar() or 0

        # Check payer enrollments
        pe_result = await db.execute(
            select(func.count()).select(PayerEnrollment).where(
                PayerEnrollment.practice_id == practice_id,
                PayerEnrollment.is_active == True,
            )
        )
        payers_count = pe_result.scalar() or 0

        # Check fee schedules (payer enrollments with fee_schedule_id set)
        fs_result = await db.execute(
            select(func.count()).select(PayerEnrollment).where(
                PayerEnrollment.practice_id == practice_id,
                PayerEnrollment.is_active == True,
                PayerEnrollment.fee_schedule_id.isnot(None),
            )
        )
        fee_schedules_count = fs_result.scalar() or 0

        # Check clearinghouse config (payer enrollments with clearinghouse set)
        ch_result = await db.execute(
            select(func.count()).select(PayerEnrollment).where(
                PayerEnrollment.practice_id == practice_id,
                PayerEnrollment.is_active == True,
                PayerEnrollment.clearinghouse.isnot(None),
                PayerEnrollment.sender_id.isnot(None),
            )
        )
        clearinghouse_count = ch_result.scalar() or 0

        # Check service agreement
        sa_result = await db.execute(
            select(func.count()).select(ServiceAgreement).where(
                ServiceAgreement.practice_id == practice_id,
                ServiceAgreement.is_active == True,
            )
        )
        agreements_count = sa_result.scalar() or 0

        # Check portal users (same as providers)
        pu_result = await db.execute(
            select(func.count()).select(User).where(
                User.practice_id == practice_id,
                User.user_type == "provider",
                User.is_active == True,
            )
        )
        portal_users_count = pu_result.scalar() or 0

        checklist = {
            "practice_created": True,
            "providers_added": providers_count > 0,
            "locations_added": locations_count > 0,
            "payers_enrolled": payers_count > 0,
            "fee_schedules_loaded": fee_schedules_count > 0,
            "clearinghouse_configured": clearinghouse_count > 0,
            "service_agreement_set": agreements_count > 0,
            "portal_users_created": portal_users_count > 0,
            "initial_data_migrated": False,  # Always False for now
        }
        checklist["go_live_ready"] = all(
            v for k, v in checklist.items() if k != "initial_data_migrated"
        )
        return checklist


# Module-level singletons
practice_service = PracticeService()
provider_service = ProviderService()
payer_enrollment_service = PayerEnrollmentService()
service_agreement_service = ServiceAgreementService()
staff_assignment_service = StaffAssignmentService()
portal_user_service = PortalUserService()
onboarding_service = OnboardingService()