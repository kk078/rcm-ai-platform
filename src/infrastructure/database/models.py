"""
SQLAlchemy ORM models for Aethera AI.

Defines all database tables for the multi-tenant third-party medical billing platform.
Every tenant-scoped table has practice_id with Row-Level Security enforced at the DB level.

Model declaration order follows FK dependency: referenced tables before referencing tables.
"""

import uuid
from datetime import date, datetime, timezone


def utcnow():
    """Return naive UTC datetime for TIMESTAMP WITHOUT TIME ZONE columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.session import Base
from src.infrastructure.auth.encryption import EncryptedString


# ── Mixins ──────────────────────────────────────────────────────────────


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: utcnow(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: utcnow(),
        onupdate=lambda: utcnow(),
        nullable=False,
    )


# ── Multi-Tenant Root ────────────────────────────────────────────────────


class Practice(Base, TimestampMixin):
    __tablename__ = "practices"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_name: Mapped[str] = mapped_column(String(255), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(255))
    tin: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    group_npi: Mapped[str | None] = mapped_column(String(10))
    specialty_primary: Mapped[str | None] = mapped_column(String(100))
    specialty_codes: Mapped[list[str] | None] = mapped_column(ARRAY(String(20)))
    address_line_1: Mapped[str | None] = mapped_column(Text)
    address_line_2: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(2))
    zip_code: Mapped[str | None] = mapped_column(String(10))
    phone: Mapped[str | None] = mapped_column(String(20))
    fax: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(255))
    website: Mapped[str | None] = mapped_column(String(500))
    contact_name: Mapped[str | None] = mapped_column(String(200))
    contact_phone: Mapped[str | None] = mapped_column(String(20))
    contact_email: Mapped[str | None] = mapped_column(String(255))

    # Onboarding
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="onboarding")
    onboarded_at: Mapped[datetime | None]
    go_live_date: Mapped[date | None]
    terminated_at: Mapped[datetime | None]
    termination_reason: Mapped[str | None] = mapped_column(Text)

    # Configuration
    timezone: Mapped[str] = mapped_column(String(50), nullable=False, default="America/New_York")
    intake_method: Mapped[str] = mapped_column(String(20), nullable=False, default="portal")
    default_clearinghouse: Mapped[str | None] = mapped_column(String(100))

    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID, ForeignKey("users.id", use_alter=True, name="fk_practices_created_by")
    )

    # Relationships
    locations: Mapped[list["PracticeLocation"]] = relationship(back_populates="practice", lazy="selectin")
    service_agreements: Mapped[list["ServiceAgreement"]] = relationship(back_populates="practice", lazy="selectin")
    payer_enrollments: Mapped[list["PayerEnrollment"]] = relationship(back_populates="practice", lazy="selectin")
    staff_assignments: Mapped[list["StaffAssignment"]] = relationship(back_populates="practice", lazy="selectin")
    patients: Mapped[list["Patient"]] = relationship(back_populates="practice", lazy="selectin")
    encounters: Mapped[list["Encounter"]] = relationship(back_populates="practice", lazy="selectin")
    claims: Mapped[list["Claim"]] = relationship(back_populates="practice", lazy="selectin")
    charge_batches: Mapped[list["ChargeBatch"]] = relationship(back_populates="practice", lazy="selectin")
    charge_entries: Mapped[list["ChargeEntry"]] = relationship(back_populates="practice", lazy="selectin")
    work_queue_items: Mapped[list["WorkQueueItem"]] = relationship(back_populates="practice", lazy="selectin")
    client_invoices: Mapped[list["ClientInvoice"]] = relationship(back_populates="practice", lazy="selectin")
    portal_messages: Mapped[list["PortalMessage"]] = relationship(back_populates="practice", lazy="selectin")
    portal_notifications: Mapped[list["PortalNotification"]] = relationship(back_populates="practice", lazy="selectin")

    __table_args__ = (
        Index("idx_practices_status", "status"),
        Index("idx_practices_tin", "tin"),
    )


class PracticeLocation(Base):
    __tablename__ = "practice_locations"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=False)
    location_name: Mapped[str] = mapped_column(String(255), nullable=False)
    address_line_1: Mapped[str] = mapped_column(Text, nullable=False)
    address_line_2: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(2))
    zip_code: Mapped[str | None] = mapped_column(String(10))
    phone: Mapped[str | None] = mapped_column(String(20))
    fax: Mapped[str | None] = mapped_column(String(20))
    place_of_service: Mapped[str] = mapped_column(String(5), nullable=False, default="11")
    facility_npi: Mapped[str | None] = mapped_column(String(10))
    is_primary: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: utcnow(), nullable=False)

    practice: Mapped["Practice"] = relationship(back_populates="locations")

    __table_args__ = (
        Index("idx_locations_practice", "practice_id"),
    )


# ── Users & Permissions ─────────────────────────────────────────────────


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Multi-tenant fields
    user_type: Mapped[str] = mapped_column(String(20), nullable=False)  # internal, provider
    practice_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=True)
    internal_role: Mapped[str | None] = mapped_column(String(30))  # company_admin, billing_manager, coder, etc.
    provider_role: Mapped[str | None] = mapped_column(String(30))  # practice_admin, provider, office_manager, etc.
    provider_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("providers.id"), nullable=True)

    department: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(default=True)
    last_login: Mapped[datetime | None]
    mfa_enabled: Mapped[bool] = mapped_column(default=False)
    mfa_secret: Mapped[str | None] = mapped_column(EncryptedString)
    mfa_backup_codes: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_changed_at: Mapped[datetime] = mapped_column(default=lambda: utcnow(), nullable=False)
    must_change_password: Mapped[bool] = mapped_column(default=False)
    failed_login_count: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None]

    # Relationships
    practice: Mapped["Practice | None"] = relationship(back_populates=None, foreign_keys=[practice_id])
    provider_ref: Mapped["Provider | None"] = relationship(back_populates="user_account")
    staff_assignments: Mapped[list["StaffAssignment"]] = relationship(back_populates="user", lazy="selectin", foreign_keys="StaffAssignment.user_id")

    __table_args__ = (
        Index("idx_users_type", "user_type"),
        Index("idx_users_practice", "practice_id"),
        Index("idx_users_email", "email"),
    )


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    resource: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)  # read, create, update, delete, export
    conditions: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        UniqueConstraint("role", "resource", "action", name="uq_permissions_role_resource_action"),
    )


# ── Core Reference Tables (not tenant-scoped) ────────────────────────────


class Provider(Base, TimestampMixin):
    __tablename__ = "providers"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    npi: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    credential: Mapped[str | None] = mapped_column(String(20))  # MD, DO, NP, PA, etc.
    taxonomy_code: Mapped[str | None] = mapped_column(String(20))
    specialty: Mapped[str | None] = mapped_column(String(100))
    tin: Mapped[str | None] = mapped_column(EncryptedString)
    is_individual: Mapped[bool] = mapped_column(default=True)
    is_active: Mapped[bool] = mapped_column(default=True)

    # Relationships
    user_account: Mapped["User | None"] = relationship(back_populates="provider_ref")


class Payer(Base, TimestampMixin):
    __tablename__ = "payers"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    payer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    payer_id_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    payer_type: Mapped[str | None] = mapped_column(String(20))
    address: Mapped[dict | None] = mapped_column(JSONB)
    phone: Mapped[str | None] = mapped_column(String(20))
    website: Mapped[str | None] = mapped_column(String(500))
    portal_url: Mapped[str | None] = mapped_column(String(500))
    clearinghouse: Mapped[str | None] = mapped_column(String(100))
    timely_filing_days: Mapped[int] = mapped_column(default=365)
    appeal_filing_days: Mapped[int] = mapped_column(default=60)
    electronic_payer: Mapped[bool] = mapped_column(default=True)
    era_enrolled: Mapped[bool] = mapped_column(default=False)
    eft_enrolled: Mapped[bool] = mapped_column(default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=True)

    # Relationships
    fee_schedules: Mapped[list["FeeSchedule"]] = relationship(back_populates="payer", lazy="selectin")
    payer_rules: Mapped[list["PayerRule"]] = relationship(back_populates="payer", lazy="selectin")
    payer_enrollments: Mapped[list["PayerEnrollment"]] = relationship(back_populates="payer", lazy="selectin")

    __table_args__ = (
        Index("idx_payers_pid", "payer_id_number"),
        Index("idx_payers_type", "payer_type"),
    )


# ── Tenant-Scoped Core Tables ──────────────────────────────────────────


class Patient(Base, TimestampMixin):
    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=False)
    mrn: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    first_name: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    last_name: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    gender: Mapped[str | None] = mapped_column(String(10))
    ssn_encrypted: Mapped[str | None] = mapped_column(EncryptedString)
    address_line_1: Mapped[str | None] = mapped_column(Text)
    address_line_2: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(2))
    zip_code: Mapped[str | None] = mapped_column(String(10))
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)

    practice: Mapped["Practice"] = relationship(back_populates="patients")
    coverages: Mapped[list["Coverage"]] = relationship(back_populates="patient", lazy="selectin")
    encounters: Mapped[list["Encounter"]] = relationship(back_populates="patient", lazy="selectin")

    __table_args__ = (
        Index("idx_patients_mrn", "mrn"),
        Index("idx_patients_name", "last_name", "first_name"),
        Index("idx_patients_dob", "date_of_birth"),
        Index("idx_patients_practice", "practice_id"),
    )


class Coverage(Base, TimestampMixin):
    __tablename__ = "coverages"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("patients.id"), nullable=False)
    payer_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("payers.id"), nullable=False)
    member_id: Mapped[str] = mapped_column(String(50), nullable=False)
    group_number: Mapped[str | None] = mapped_column(String(50))
    plan_name: Mapped[str | None] = mapped_column(String(255))
    plan_type: Mapped[str | None] = mapped_column(String(20))  # HMO, PPO, POS, EPO, Medicare, Medicaid
    coverage_type: Mapped[str] = mapped_column(String(20), nullable=False)  # primary, secondary, tertiary
    subscriber_relation: Mapped[str | None] = mapped_column(String(20))  # self, spouse, child, other
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    termination_date: Mapped[date | None]
    copay_amount: Mapped[float | None]  # DECIMAL(10,2)
    deductible_amount: Mapped[float | None]
    deductible_met: Mapped[float | None]
    coinsurance_pct: Mapped[float | None]  # DECIMAL(5,2)
    verified_at: Mapped[datetime | None]
    verified_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("users.id"))
    is_active: Mapped[bool] = mapped_column(default=True)

    patient: Mapped["Patient"] = relationship(back_populates="coverages")
    payer: Mapped["Payer"] = relationship()

    __table_args__ = (
        Index("idx_coverages_patient", "patient_id"),
        Index("idx_coverages_payer", "payer_id"),
        Index("idx_coverages_member", "member_id"),
        Index("idx_coverages_practice", "practice_id"),
        CheckConstraint(
            "plan_type IS NULL OR plan_type IN ('HMO','PPO','POS','EPO','IPA','Indemnity','HDHP','Medicare','Medicaid','Other')",
            name="ck_coverages_plan_type",
        ),
    )


class Encounter(Base, TimestampMixin):
    __tablename__ = "encounters"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("patients.id"), nullable=False)
    provider_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("providers.id"), nullable=False)
    encounter_type: Mapped[str] = mapped_column(String(20), nullable=False)  # office, inpatient, outpatient, ER, telehealth
    encounter_date: Mapped[date] = mapped_column(Date, nullable=False)
    admit_date: Mapped[date | None]
    discharge_date: Mapped[date | None]
    place_of_service: Mapped[str] = mapped_column(String(5), nullable=False)
    referring_provider_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("providers.id"))
    prior_auth_number: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)
    document_ids: Mapped[list[uuid.UUID] | None] = mapped_column(ARRAY(PG_UUID))
    status: Mapped[str] = mapped_column(String(20), default="open")

    practice: Mapped["Practice"] = relationship(back_populates="encounters")
    patient: Mapped["Patient"] = relationship(back_populates="encounters")
    provider: Mapped["Provider"] = relationship(foreign_keys=[provider_id])
    referring_provider: Mapped["Provider | None"] = relationship(foreign_keys=[referring_provider_id])
    coding_sessions: Mapped[list["CodingSession"]] = relationship(back_populates="encounter", lazy="selectin")

    __table_args__ = (
        Index("idx_encounters_patient", "patient_id"),
        Index("idx_encounters_date", "encounter_date"),
        Index("idx_encounters_status", "status"),
        Index("idx_encounters_practice", "practice_id"),
    )


# ── Fee Schedules & Payer Rules (not tenant-scoped) ─────────────────────


class FeeSchedule(Base, TimestampMixin):
    __tablename__ = "fee_schedules"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    payer_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("payers.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    termination_date: Mapped[date | None]
    is_active: Mapped[bool] = mapped_column(default=True)

    payer: Mapped["Payer"] = relationship(back_populates="fee_schedules")
    rates: Mapped[list["FeeScheduleRate"]] = relationship(back_populates="fee_schedule", lazy="selectin")


class FeeScheduleRate(Base):
    __tablename__ = "fee_schedule_rates"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    fee_schedule_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("fee_schedules.id"), nullable=False)
    cpt_code: Mapped[str] = mapped_column(String(10), nullable=False)
    modifier: Mapped[str | None] = mapped_column(String(5))
    place_of_service: Mapped[str | None] = mapped_column(String(5))
    allowed_amount: Mapped[float] = mapped_column(nullable=False)  # DECIMAL(12,2)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)

    fee_schedule: Mapped["FeeSchedule"] = relationship(back_populates="rates")

    __table_args__ = (
        UniqueConstraint("fee_schedule_id", "cpt_code", "modifier", "place_of_service", "effective_date", name="uq_fsr_unique_rate"),
        Index("idx_fsr_schedule", "fee_schedule_id"),
        Index("idx_fsr_cpt", "cpt_code"),
    )


class PayerRule(Base, TimestampMixin):
    __tablename__ = "payer_rules"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    payer_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("payers.id"), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(30), nullable=False)
    cpt_code: Mapped[str | None] = mapped_column(String(10))
    icd10_code: Mapped[str | None] = mapped_column(String(10))
    rule_definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(255))
    effective_date: Mapped[date | None]
    termination_date: Mapped[date | None]
    is_active: Mapped[bool] = mapped_column(default=True)

    payer: Mapped["Payer"] = relationship(back_populates="payer_rules")

    __table_args__ = (
        Index("idx_payer_rules_payer", "payer_id"),
        Index("idx_payer_rules_cpt", "cpt_code"),
        Index("idx_payer_rules_type", "rule_type"),
    )


# ── Service Agreements & Payer Enrollments ──────────────────────────────


class ServiceAgreement(Base, TimestampMixin):
    __tablename__ = "service_agreements"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=False)

    # Fee model
    fee_model: Mapped[str] = mapped_column(String(20), nullable=False)  # percentage, per_claim, flat_fee, hybrid
    percentage_rate: Mapped[float | None]  # DECIMAL(5,2)
    per_claim_rate: Mapped[float | None]  # DECIMAL(10,2)
    flat_fee_monthly: Mapped[float | None]  # DECIMAL(12,2)
    hybrid_base_fee: Mapped[float | None]  # DECIMAL(12,2)
    hybrid_threshold: Mapped[float | None]  # DECIMAL(12,2)
    hybrid_overage_rate: Mapped[float | None]  # DECIMAL(5,2)

    minimum_monthly_fee: Mapped[float | None]  # DECIMAL(12,2)

    # Services included
    includes_coding: Mapped[bool] = mapped_column(default=True)
    includes_billing: Mapped[bool] = mapped_column(default=True)
    includes_posting: Mapped[bool] = mapped_column(default=True)
    includes_denials: Mapped[bool] = mapped_column(default=True)
    includes_credentialing: Mapped[bool] = mapped_column(default=False)
    includes_eligibility: Mapped[bool] = mapped_column(default=True)
    includes_patient_collections: Mapped[bool] = mapped_column(default=False)
    includes_reporting: Mapped[bool] = mapped_column(default=True)

    # SLA targets
    sla_clean_claim_rate: Mapped[float] = mapped_column(default=95.00)  # DECIMAL(5,2)
    sla_days_to_submit: Mapped[int] = mapped_column(default=2)
    sla_appeal_turnaround: Mapped[int] = mapped_column(default=5)
    sla_posting_turnaround: Mapped[int] = mapped_column(default=2)
    sla_denial_response: Mapped[int] = mapped_column(default=5)

    # Contract terms
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    termination_date: Mapped[date | None]
    auto_renew: Mapped[bool] = mapped_column(default=True)
    notice_period_days: Mapped[int] = mapped_column(default=90)
    is_active: Mapped[bool] = mapped_column(default=True)

    practice: Mapped["Practice"] = relationship(back_populates="service_agreements")

    __table_args__ = (
        Index("idx_agreements_practice", "practice_id"),
    )


# ── Eligibility Checks ──────────────────────────────────────────────────


class EligibilityCheck(TimestampMixin, Base):
    """Real-time eligibility check results for patient/coverage."""
    __tablename__ = "eligibility_checks"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("patients.id"), nullable=False)
    coverage_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("coverages.id"))
    charge_batch_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("charge_batches.id"))
    payer_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("payers.id"))
    check_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    service_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, active, inactive, error
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    deductible_total: Mapped[Numeric | None] = mapped_column(Numeric(10, 2))
    deductible_met: Mapped[Numeric | None] = mapped_column(Numeric(10, 2))
    oop_total: Mapped[Numeric | None] = mapped_column(Numeric(10, 2))
    oop_met: Mapped[Numeric | None] = mapped_column(Numeric(10, 2))
    copay: Mapped[Numeric | None] = mapped_column(Numeric(10, 2))
    coinsurance_pct: Mapped[int | None] = mapped_column(Integer)
    network_status: Mapped[str | None] = mapped_column(String(20))  # in-network, out-of-network, unknown
    plan_name: Mapped[str | None] = mapped_column(String(200))
    plan_type: Mapped[str | None] = mapped_column(String(20))  # canonical PLAN_TYPES (see core/eligibility/plan_types.py)
    group_number: Mapped[str | None] = mapped_column(String(100))
    raw_response: Mapped[dict | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    checked_by_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("users.id"))
    # Relationships
    patient: Mapped["Patient"] = relationship("Patient", foreign_keys=[patient_id], lazy="selectin")
    coverage: Mapped["Coverage | None"] = relationship("Coverage", foreign_keys=[coverage_id], lazy="selectin")
    __table_args__ = (
        Index("ix_eligibility_checks_practice_patient", "practice_id", "patient_id"),
        Index("ix_eligibility_checks_check_date", "check_date"),
        CheckConstraint(
            "plan_type IS NULL OR plan_type IN ('HMO','PPO','POS','EPO','IPA','Indemnity','HDHP','Medicare','Medicaid','Other')",
            name="ck_eligibility_checks_plan_type",
        ),
    )


# ── Prior Authorizations ────────────────────────────────────────────────


class PriorAuthorization(TimestampMixin, Base):
    """Prior authorization tracking per encounter/procedure."""
    __tablename__ = "prior_authorizations"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("patients.id"), nullable=False)
    coverage_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("coverages.id"))
    encounter_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("encounters.id"))
    claim_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("claims.id"))
    payer_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("payers.id"))
    auth_number: Mapped[str | None] = mapped_column(String(100))
    procedure_codes: Mapped[list[str] | None] = mapped_column(ARRAY(String(20)))
    diagnosis_codes: Mapped[list[str] | None] = mapped_column(ARRAY(String(20)))
    status: Mapped[str] = mapped_column(String(30), default="pending")  # pending, approved, denied, expired, cancelled
    requested_date: Mapped[date | None] = mapped_column(Date)
    approved_date: Mapped[date | None] = mapped_column(Date)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    approved_units: Mapped[int | None] = mapped_column(Integer)
    approved_visits: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("users.id"))
    denial_reason: Mapped[str | None] = mapped_column(Text)
    appeal_deadline: Mapped[date | None] = mapped_column(Date)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)
    # Relationships
    patient: Mapped["Patient"] = relationship("Patient", lazy="selectin")
    encounter: Mapped["Encounter | None"] = relationship("Encounter", lazy="selectin")
    __table_args__ = (
        Index("ix_prior_auth_practice_patient", "practice_id", "patient_id"),
        Index("ix_prior_auth_status", "status"),
        Index("ix_prior_auth_valid_to", "valid_to"),
    )


# ── Patient Statements ──────────────────────────────────────────────────


class PatientStatement(TimestampMixin, Base):
    """Patient responsibility statements and balance tracking."""
    __tablename__ = "patient_statements"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("patients.id"), nullable=False)
    statement_number: Mapped[str] = mapped_column(String(50), unique=True)
    statement_date: Mapped[date] = mapped_column(Date, default=date.today)
    due_date: Mapped[date | None] = mapped_column(Date)
    total_charges: Mapped[Numeric] = mapped_column(Numeric(12, 2), default=0)
    total_insurance_paid: Mapped[Numeric] = mapped_column(Numeric(12, 2), default=0)
    total_adjustments: Mapped[Numeric] = mapped_column(Numeric(12, 2), default=0)
    total_patient_paid: Mapped[Numeric] = mapped_column(Numeric(12, 2), default=0)
    balance_due: Mapped[Numeric] = mapped_column(Numeric(12, 2), default=0)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open, paid, partial, collections, voided
    delivery_method: Mapped[str | None] = mapped_column(String(20))  # email, sms, mail, portal
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payment_reference: Mapped[str | None] = mapped_column(String(100))
    line_items: Mapped[dict | None] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text)
    # Relationships
    patient: Mapped["Patient"] = relationship("Patient", lazy="selectin")
    __table_args__ = (
        Index("ix_patient_statements_practice_patient", "practice_id", "patient_id"),
        Index("ix_patient_statements_status", "status"),
    )


# ── Document Attachments ────────────────────────────────────────────────


class DocumentAttachment(TimestampMixin, Base):
    """Document management — files linked to any entity."""
    __tablename__ = "document_attachments"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50))  # claim, denial, appeal, encounter, patient, prior_auth
    entity_id: Mapped[uuid.UUID] = mapped_column(PG_UUID)
    file_name: Mapped[str] = mapped_column(String(500))
    file_size: Mapped[int | None] = mapped_column(Integer)  # bytes
    mime_type: Mapped[str | None] = mapped_column(String(100))
    storage_key: Mapped[str] = mapped_column(String(1000))  # S3/R2 object key
    storage_url: Mapped[str | None] = mapped_column(String(2000))  # signed URL (ephemeral)
    document_type: Mapped[str | None] = mapped_column(String(50))  # eob, appeal_letter, clinical_note, auth, other
    description: Mapped[str | None] = mapped_column(Text)
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("users.id"))
    is_phi: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (
        Index("ix_document_attachments_entity", "entity_type", "entity_id"),
        Index("ix_document_attachments_practice", "practice_id"),
    )


# ── Notification Rules & Log ────────────────────────────────────────────


class NotificationRule(TimestampMixin, Base):
    """Configurable rules for when to send notifications and via which channels."""
    __tablename__ = "notification_rules"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("practices.id"))  # None = global
    event_type: Mapped[str] = mapped_column(String(100))  # sla_breach, denial_deadline, era_posted, appeal_due, eligibility_failed
    role_filter: Mapped[list[str] | None] = mapped_column(ARRAY(String(50)))  # roles to notify; None = all
    channels: Mapped[list[str]] = mapped_column(ARRAY(String(20)))  # email, sms, portal
    threshold_hours: Mapped[int | None] = mapped_column(Integer)  # for deadline-based triggers
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    template_subject: Mapped[str | None] = mapped_column(String(500))
    template_body: Mapped[str | None] = mapped_column(Text)


class NotificationLog(TimestampMixin, Base):
    """Log of all notifications sent."""
    __tablename__ = "notification_log"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("practices.id"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("users.id"))
    event_type: Mapped[str] = mapped_column(String(100))
    channel: Mapped[str] = mapped_column(String(20))  # email, sms, portal
    recipient: Mapped[str | None] = mapped_column(String(500))  # email or phone
    subject: Mapped[str | None] = mapped_column(String(500))
    body: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="sent")  # sent, failed, bounced
    entity_type: Mapped[str | None] = mapped_column(String(50))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID)
    error_message: Mapped[str | None] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(String(200))  # Twilio/SMTP message ID
    __table_args__ = (Index("ix_notification_log_user_created", "user_id", "created_at"),)


# ── AI Coding Feedback ──────────────────────────────────────────────────


class AICodingFeedback(TimestampMixin, Base):
    """Captures coder overrides of AI suggestions for model improvement."""
    __tablename__ = "ai_coding_feedback"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=False)
    coding_session_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("coding_sessions.id"), nullable=False)
    encounter_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("encounters.id"))
    coder_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("users.id"), nullable=False)
    ai_suggested_dx: Mapped[list[str] | None] = mapped_column(ARRAY(String(20)))
    ai_suggested_cpt: Mapped[list[str] | None] = mapped_column(ARRAY(String(20)))
    final_dx: Mapped[list[str] | None] = mapped_column(ARRAY(String(20)))
    final_cpt: Mapped[list[str] | None] = mapped_column(ARRAY(String(20)))
    dx_accepted: Mapped[bool | None] = mapped_column(Boolean)
    cpt_accepted: Mapped[bool | None] = mapped_column(Boolean)
    override_reason: Mapped[str | None] = mapped_column(Text)
    specialty: Mapped[str | None] = mapped_column(String(100))
    ai_provider: Mapped[str | None] = mapped_column(String(50))  # ollama, anthropic
    ai_model: Mapped[str | None] = mapped_column(String(100))
    __table_args__ = (
        Index("ix_ai_coding_feedback_practice_specialty", "practice_id", "specialty"),
        Index("ix_ai_coding_feedback_coder", "coder_id"),
    )


# ── EHR Connections ─────────────────────────────────────────────────────


class EHRConnection(TimestampMixin, Base):
    """Configuration for EHR/EMR/PMS integration per practice."""
    __tablename__ = "ehr_connections"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=False, unique=True)
    ehr_type: Mapped[str] = mapped_column(String(50))  # fhir_r4, athena, kareo, drchrono, hl7v2, sftp_csv, webhook, zapier
    ehr_name: Mapped[str | None] = mapped_column(String(200))  # e.g. "Epic", "Kareo"
    base_url: Mapped[str | None] = mapped_column(String(2000))
    client_id: Mapped[str | None] = mapped_column(String(500))
    client_secret_enc: Mapped[str | None] = mapped_column(Text)  # encrypted
    access_token_enc: Mapped[str | None] = mapped_column(Text)   # encrypted, short-lived
    refresh_token_enc: Mapped[str | None] = mapped_column(Text)  # encrypted
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sftp_host: Mapped[str | None] = mapped_column(String(500))
    sftp_port: Mapped[int | None] = mapped_column(Integer, default=22)
    sftp_username: Mapped[str | None] = mapped_column(String(200))
    sftp_password_enc: Mapped[str | None] = mapped_column(Text)  # encrypted
    sftp_path: Mapped[str | None] = mapped_column(String(1000))
    webhook_secret: Mapped[str | None] = mapped_column(String(500))
    fhir_patient_scope: Mapped[bool] = mapped_column(Boolean, default=True)
    fhir_coverage_scope: Mapped[bool] = mapped_column(Boolean, default=True)
    fhir_encounter_scope: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[str | None] = mapped_column(String(20))  # success, failed, partial
    last_sync_count: Mapped[int | None] = mapped_column(Integer)
    config: Mapped[dict | None] = mapped_column(JSONB)  # extra vendor-specific config


class EHRSyncLog(TimestampMixin, Base):
    """Log of EHR sync operations."""
    __tablename__ = "ehr_sync_log"
    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    ehr_connection_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("ehr_connections.id"), nullable=False)
    practice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=False)
    sync_type: Mapped[str] = mapped_column(String(50))  # patients, coverage, encounters, charges
    trigger: Mapped[str] = mapped_column(String(50))  # scheduled, webhook, manual
    records_fetched: Mapped[int] = mapped_column(Integer, default=0)
    records_created: Mapped[int] = mapped_column(Integer, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, default=0)
    records_skipped: Mapped[int] = mapped_column(Integer, default=0)
    records_errored: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running, success, failed, partial
    error_details: Mapped[dict | None] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("ix_ehr_sync_log_connection", "ehr_connection_id", "started_at"),)


class PayerEnrollment(Base, TimestampMixin):
    __tablename__ = "payer_enrollments"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=False)
    payer_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("payers.id"), nullable=False)

    group_number: Mapped[str | None] = mapped_column(String(50))
    provider_numbers: Mapped[dict | None] = mapped_column(JSONB)
    edi_payer_id: Mapped[str | None] = mapped_column(String(20))

    # ERA / EFT
    era_enrolled: Mapped[bool] = mapped_column(default=False)
    era_enrollment_date: Mapped[date | None]
    eft_enrolled: Mapped[bool] = mapped_column(default=False)
    eft_enrollment_date: Mapped[date | None]

    # Clearinghouse
    clearinghouse: Mapped[str | None] = mapped_column(String(100))
    sender_id: Mapped[str | None] = mapped_column(String(50))
    receiver_id: Mapped[str | None] = mapped_column(String(50))

    # Payer-specific config
    timely_filing_days: Mapped[int | None]
    appeal_filing_days: Mapped[int | None]
    appeal_address: Mapped[str | None] = mapped_column(Text)
    appeal_fax: Mapped[str | None] = mapped_column(String(20))
    payer_portal_url: Mapped[str | None] = mapped_column(String(500))
    payer_portal_login: Mapped[str | None] = mapped_column(EncryptedString)
    payer_phone: Mapped[str | None] = mapped_column(String(20))
    payer_rep_name: Mapped[str | None] = mapped_column(String(200))

    fee_schedule_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("fee_schedules.id"))
    is_active: Mapped[bool] = mapped_column(default=True)

    practice: Mapped["Practice"] = relationship(back_populates="payer_enrollments")
    payer: Mapped["Payer"] = relationship(back_populates="payer_enrollments")

    __table_args__ = (
        UniqueConstraint("practice_id", "payer_id", name="uq_payer_enrollment_practice_payer"),
        Index("idx_enrollments_practice", "practice_id"),
        Index("idx_enrollments_payer", "payer_id"),
    )


# ── Claims & Billing ────────────────────────────────────────────────────


class Claim(Base, TimestampMixin):
    __tablename__ = "claims"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=False)
    claim_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    encounter_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("encounters.id"), nullable=False)
    patient_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("patients.id"), nullable=False)
    payer_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("payers.id"), nullable=False)
    coverage_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("coverages.id"), nullable=False)
    rendering_provider: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("providers.id"), nullable=False)
    billing_provider: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("providers.id"), nullable=False)
    claim_type: Mapped[str] = mapped_column(String(5), nullable=False)  # 837P, 837I
    frequency_code: Mapped[str] = mapped_column(String(2), default="1")
    total_charge: Mapped[float] = mapped_column(nullable=False)  # DECIMAL(12,2)
    total_paid: Mapped[float] = mapped_column(default=0)
    total_adjusted: Mapped[float] = mapped_column(default=0)
    patient_responsibility: Mapped[float] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    submission_date: Mapped[datetime | None]
    adjudication_date: Mapped[datetime | None]
    timely_filing_deadline: Mapped[date | None]
    clearinghouse_id: Mapped[str | None] = mapped_column(String(100))
    clearinghouse_ref: Mapped[str | None] = mapped_column(String(100))
    edi_837_file_id: Mapped[uuid.UUID | None]
    scrub_score: Mapped[int | None]
    denial_risk_score: Mapped[float | None]  # DECIMAL(5,4)
    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("users.id"))

    practice: Mapped["Practice"] = relationship(back_populates="claims")
    encounter: Mapped["Encounter"] = relationship()
    patient: Mapped["Patient"] = relationship()
    payer: Mapped["Payer"] = relationship()
    lines: Mapped[list["ClaimLine"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan", lazy="selectin"
    )
    diagnoses: Mapped[list["ClaimDiagnosis"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan", lazy="selectin"
    )
    scrub_results: Mapped[list["ClaimScrubResult"]] = relationship(back_populates="claim", lazy="selectin")

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','scrubbing','scrub_failed','ready','submitted',"
            "'accepted','rejected','paid','partial_paid','denied','appealed','closed')",
            name="ck_claims_status",
        ),
        Index("idx_claims_number", "claim_number"),
        Index("idx_claims_patient", "patient_id"),
        Index("idx_claims_payer", "payer_id"),
        Index("idx_claims_status", "status"),
        Index("idx_claims_submission", "submission_date"),
        Index("idx_claims_encounter", "encounter_id"),
        Index("idx_claims_practice", "practice_id"),
    )


class ClaimLine(Base):
    __tablename__ = "claim_lines"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=False)
    claim_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("claims.id", ondelete="CASCADE"), nullable=False)
    line_number: Mapped[int] = mapped_column(nullable=False)
    cpt_code: Mapped[str] = mapped_column(String(10), nullable=False)
    cpt_description: Mapped[str | None] = mapped_column(Text)
    icd_pointer_1: Mapped[str | None] = mapped_column(String(10))
    icd_pointer_2: Mapped[str | None] = mapped_column(String(10))
    icd_pointer_3: Mapped[str | None] = mapped_column(String(10))
    icd_pointer_4: Mapped[str | None] = mapped_column(String(10))
    modifier_1: Mapped[str | None] = mapped_column(String(5))
    modifier_2: Mapped[str | None] = mapped_column(String(5))
    modifier_3: Mapped[str | None] = mapped_column(String(5))
    modifier_4: Mapped[str | None] = mapped_column(String(5))
    units: Mapped[float] = mapped_column(default=1)  # DECIMAL(10,2)
    charge_amount: Mapped[float] = mapped_column(nullable=False)  # DECIMAL(12,2)
    paid_amount: Mapped[float] = mapped_column(default=0)
    allowed_amount: Mapped[float | None]
    service_date_from: Mapped[date] = mapped_column(Date, nullable=False)
    service_date_to: Mapped[date | None]
    place_of_service: Mapped[str | None] = mapped_column(String(5))
    ndc_code: Mapped[str | None] = mapped_column(String(20))
    revenue_code: Mapped[str | None] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default="active")

    claim: Mapped["Claim"] = relationship(back_populates="lines")

    __table_args__ = (
        UniqueConstraint("claim_id", "line_number", name="uq_claim_line_number"),
        Index("idx_claim_lines_claim", "claim_id"),
        Index("idx_claim_lines_cpt", "cpt_code"),
    )


class ClaimDiagnosis(Base):
    __tablename__ = "claim_diagnoses"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=False)
    claim_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("claims.id", ondelete="CASCADE"), nullable=False)
    sequence_number: Mapped[int] = mapped_column(nullable=False)
    icd10_code: Mapped[str] = mapped_column(String(10), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_principal: Mapped[bool] = mapped_column(default=False)

    claim: Mapped["Claim"] = relationship(back_populates="diagnoses")

    __table_args__ = (
        UniqueConstraint("claim_id", "sequence_number", name="uq_claim_dx_sequence"),
        Index("idx_claim_dx_claim", "claim_id"),
        Index("idx_claim_dx_code", "icd10_code"),
    )


class ClaimScrubResult(Base):
    __tablename__ = "claim_scrub_results"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=False)
    claim_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("claims.id"), nullable=False)
    claim_line_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("claim_lines.id"))
    rule_type: Mapped[str] = mapped_column(String(30), nullable=False)
    rule_id: Mapped[str | None] = mapped_column(String(100))
    severity: Mapped[str] = mapped_column(String(10), nullable=False)  # error, warning, info
    message: Mapped[str] = mapped_column(Text, nullable=False)
    suggestion: Mapped[str | None] = mapped_column(Text)
    auto_fixable: Mapped[bool] = mapped_column(default=False)
    auto_fixed: Mapped[bool] = mapped_column(default=False)
    resolved: Mapped[bool] = mapped_column(default=False)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=lambda: utcnow(), nullable=False)

    claim: Mapped["Claim"] = relationship(back_populates="scrub_results")

    __table_args__ = (
        Index("idx_scrub_claim", "claim_id"),
        Index("idx_scrub_severity", "severity"),
    )


class CodingSession(Base, TimestampMixin):
    __tablename__ = "coding_sessions"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=False)
    encounter_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("encounters.id"), nullable=False)
    coder_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("users.id"))
    document_ids: Mapped[list[uuid.UUID] | None] = mapped_column(ARRAY(PG_UUID))

    # AI processing
    nlp_extraction: Mapped[dict | None] = mapped_column(JSONB)
    ai_model_version: Mapped[str | None] = mapped_column(String(50))
    processing_time_ms: Mapped[int | None]
    token_count: Mapped[int | None]

    # Results
    suggested_codes: Mapped[dict] = mapped_column(JSONB, nullable=False)
    final_codes: Mapped[dict | None] = mapped_column(JSONB)

    # Audit
    review_started_at: Mapped[datetime | None]
    review_completed_at: Mapped[datetime | None]
    review_time_seconds: Mapped[int | None]
    coder_changes: Mapped[dict | None] = mapped_column(JSONB)

    status: Mapped[str] = mapped_column(String(20), default="processing")

    encounter: Mapped["Encounter"] = relationship(back_populates="coding_sessions")

    __table_args__ = (
        Index("idx_coding_encounter", "encounter_id"),
        Index("idx_coding_status", "status"),
        Index("idx_coding_coder", "coder_id"),
        Index("idx_coding_practice", "practice_id"),
    )


# ── Payments ────────────────────────────────────────────────────────────


class PaymentBatch(Base):
    __tablename__ = "payment_batches"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=False)
    payer_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("payers.id"), nullable=False)
    check_number: Mapped[str | None] = mapped_column(String(50))
    eft_trace: Mapped[str | None] = mapped_column(String(50))
    payment_method: Mapped[str | None] = mapped_column(String(20))  # check, eft, virtual_card
    total_paid: Mapped[float] = mapped_column(nullable=False)  # DECIMAL(14,2)
    total_claims: Mapped[int] = mapped_column(nullable=False)
    era_file_id: Mapped[uuid.UUID | None]
    production_date: Mapped[date | None]
    deposit_date: Mapped[date | None]
    posted_date: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(String(20), default="received")
    posted_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("users.id"))
    auto_posted: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: utcnow(), nullable=False)

    __table_args__ = (
        Index("idx_payment_batch_payer", "payer_id"),
        Index("idx_payment_batch_check", "check_number"),
        Index("idx_payment_batch_status", "status"),
        Index("idx_payment_batch_practice", "practice_id"),
    )


class PaymentLine(Base):
    __tablename__ = "payment_lines"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=False)
    batch_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("payment_batches.id"), nullable=False)
    claim_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("claims.id"))
    claim_line_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("claim_lines.id"))
    patient_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("patients.id"))
    claim_number_reported: Mapped[str | None] = mapped_column(String(50))
    service_date: Mapped[date | None]
    cpt_code: Mapped[str | None] = mapped_column(String(10))
    billed_amount: Mapped[float | None]  # DECIMAL(12,2)
    allowed_amount: Mapped[float | None]
    paid_amount: Mapped[float] = mapped_column(nullable=False)  # DECIMAL(12,2)
    patient_responsibility: Mapped[float] = mapped_column(default=0)
    match_status: Mapped[str] = mapped_column(String(20), default="unmatched")
    match_confidence: Mapped[float | None]  # DECIMAL(5,4)
    is_underpaid: Mapped[bool] = mapped_column(default=False)
    underpayment_amount: Mapped[float | None]
    created_at: Mapped[datetime] = mapped_column(default=lambda: utcnow(), nullable=False)

    __table_args__ = (
        Index("idx_payment_line_batch", "batch_id"),
        Index("idx_payment_line_claim", "claim_id"),
        Index("idx_payment_line_match", "match_status"),
    )


class Adjustment(Base):
    __tablename__ = "adjustments"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=False)
    payment_line_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("payment_lines.id"), nullable=False)
    group_code: Mapped[str] = mapped_column(String(5), nullable=False)  # CO, PR, OA, PI, CR
    reason_code: Mapped[str] = mapped_column(String(10), nullable=False)  # CARC codes
    amount: Mapped[float] = mapped_column(nullable=False)  # DECIMAL(12,2)
    remark_codes: Mapped[list[str] | None] = mapped_column(ARRAY(String(20)))
    is_denial: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: utcnow(), nullable=False)

    __table_args__ = (
        Index("idx_adj_payment_line", "payment_line_id"),
        Index("idx_adj_reason", "reason_code"),
        Index("idx_adj_practice", "practice_id"),
    )


class Denial(Base, TimestampMixin):
    __tablename__ = "denials"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=False)
    claim_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("claims.id"), nullable=False)
    claim_line_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("claim_lines.id"))
    adjustment_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("adjustments.id"))
    payer_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("payers.id"), nullable=False)
    denial_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason_code: Mapped[str] = mapped_column(String(10), nullable=False)  # CARC
    remark_codes: Mapped[list[str] | None] = mapped_column(ARRAY(String(20)))
    denial_amount: Mapped[float] = mapped_column(nullable=False)  # DECIMAL(12,2)

    # AI classification
    category: Mapped[str | None] = mapped_column(String(30))
    subcategory: Mapped[str | None] = mapped_column(String(50))
    root_cause: Mapped[str | None] = mapped_column(Text)

    # Priority scoring
    priority_score: Mapped[float | None]  # DECIMAL(5,4)
    recovery_probability: Mapped[float | None]  # DECIMAL(5,4)

    # Workflow
    status: Mapped[str] = mapped_column(String(20), default="new")
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("users.id"))
    appeal_deadline: Mapped[date | None]
    timely_filing_deadline: Mapped[date | None]

    # Resolution
    resolution: Mapped[str | None] = mapped_column(String(20))
    recovered_amount: Mapped[float | None]
    resolved_at: Mapped[datetime | None]
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("users.id"))

    # Relationships
    appeals: Mapped[list["Appeal"]] = relationship(back_populates="denial", lazy="selectin")

    __table_args__ = (
        Index("idx_denials_claim", "claim_id"),
        Index("idx_denials_payer", "payer_id"),
        Index("idx_denials_status", "status"),
        Index("idx_denials_category", "category"),
        Index("idx_denials_priority", "priority_score", postgresql_using="btree"),
        Index("idx_denials_deadline", "appeal_deadline"),
        Index("idx_denials_practice", "practice_id"),
    )


class Appeal(Base, TimestampMixin):
    __tablename__ = "appeals"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=False)
    denial_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("denials.id"), nullable=False)
    appeal_level: Mapped[int] = mapped_column(default=1)
    appeal_type: Mapped[str | None] = mapped_column(String(30))

    # Content
    letter_content: Mapped[str] = mapped_column(Text, nullable=False)
    letter_file_id: Mapped[uuid.UUID | None]
    supporting_docs: Mapped[list[uuid.UUID] | None] = mapped_column(ARRAY(PG_UUID))

    # AI metadata
    ai_generated: Mapped[bool] = mapped_column(default=True)
    ai_confidence: Mapped[float | None]  # DECIMAL(5,4)
    prompt_template_id: Mapped[str | None] = mapped_column(String(100))
    guidelines_cited: Mapped[list[str] | None] = mapped_column(ARRAY(Text))

    # Tracking
    status: Mapped[str] = mapped_column(String(20), default="draft")
    submitted_date: Mapped[date | None]
    decision_date: Mapped[date | None]
    decision: Mapped[str | None] = mapped_column(String(20))
    decision_amount: Mapped[float | None]
    follow_up_date: Mapped[date | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("users.id"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("users.id"))

    denial: Mapped["Denial"] = relationship(back_populates="appeals")

    __table_args__ = (
        Index("idx_appeals_denial", "denial_id"),
        Index("idx_appeals_status", "status"),
        Index("idx_appeals_follow_up", "follow_up_date"),
        Index("idx_appeals_practice", "practice_id"),
    )


# ── Eligibility Checks ──────────────────────────────────────────────────


class ChargeBatch(Base):
    __tablename__ = "charge_batches"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=False)
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("users.id"))
    intake_method: Mapped[str] = mapped_column(String(20), nullable=False)  # portal, upload, batch_import, ehr, fax
    source_file_id: Mapped[uuid.UUID | None]
    total_charges: Mapped[int] = mapped_column(default=0)
    processed_charges: Mapped[int] = mapped_column(default=0)
    error_charges: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(20), default="received")
    received_at: Mapped[datetime] = mapped_column(default=lambda: utcnow(), nullable=False)
    processed_at: Mapped[datetime | None]
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=lambda: utcnow(), nullable=False)

    practice: Mapped["Practice"] = relationship(back_populates="charge_batches")

    __table_args__ = (
        Index("idx_charge_batches_practice", "practice_id"),
        Index("idx_charge_batches_status", "status"),
    )


class ChargeEntry(Base, TimestampMixin):
    __tablename__ = "charge_entries"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=False)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("charge_batches.id"))
    encounter_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("encounters.id"))

    # Patient info (as submitted)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("patients.id"))
    patient_name_submitted: Mapped[str | None] = mapped_column(String(200))
    patient_dob_submitted: Mapped[date | None]
    patient_mrn_submitted: Mapped[str | None] = mapped_column(String(50))

    # Provider info
    rendering_provider_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("providers.id"))
    referring_provider_name: Mapped[str | None] = mapped_column(String(200))
    referring_provider_npi: Mapped[str | None] = mapped_column(String(10))

    # Service info
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    place_of_service: Mapped[str | None] = mapped_column(String(5))
    location_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("practice_locations.id"))

    # Codes
    diagnosis_codes: Mapped[list[str] | None] = mapped_column(ARRAY(String(10)))
    procedure_codes: Mapped[dict | None] = mapped_column(JSONB)
    needs_coding: Mapped[bool] = mapped_column(default=False)

    # Clinical documentation
    clinical_notes: Mapped[str | None] = mapped_column(Text)
    document_ids: Mapped[list[uuid.UUID] | None] = mapped_column(ARRAY(PG_UUID))
    superbill_image_id: Mapped[uuid.UUID | None]

    # Insurance
    primary_payer_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("payers.id"))
    member_id: Mapped[str | None] = mapped_column(String(50))
    authorization_number: Mapped[str | None] = mapped_column(String(50))

    # Status
    status: Mapped[str] = mapped_column(String(20), default="received")
    validation_errors: Mapped[dict | None] = mapped_column(JSONB)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("users.id"))

    # Communication
    provider_notified: Mapped[bool] = mapped_column(default=False)
    provider_response: Mapped[str | None] = mapped_column(Text)

    practice: Mapped["Practice"] = relationship(back_populates="charge_entries")

    __table_args__ = (
        Index("idx_charges_practice", "practice_id"),
        Index("idx_charges_status", "status"),
        Index("idx_charges_assigned", "assigned_to"),
        Index("idx_charges_date", "service_date"),
    )


# ── Portal Communication ────────────────────────────────────────────────


class PortalMessage(Base):
    __tablename__ = "portal_messages"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=False)
    thread_id: Mapped[uuid.UUID | None]
    sender_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("users.id"), nullable=False)
    sender_type: Mapped[str] = mapped_column(String(20), nullable=False)  # internal_staff, provider
    subject: Mapped[str | None] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    attachments: Mapped[list[uuid.UUID] | None] = mapped_column(ARRAY(PG_UUID))

    # Context linking
    related_claim_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("claims.id"))
    related_charge_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("charge_entries.id"))
    related_denial_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("denials.id"))

    # Status
    is_read: Mapped[bool] = mapped_column(default=False)
    read_at: Mapped[datetime | None]
    is_urgent: Mapped[bool] = mapped_column(default=False)
    requires_response: Mapped[bool] = mapped_column(default=False)
    response_deadline: Mapped[datetime | None]

    created_at: Mapped[datetime] = mapped_column(default=lambda: utcnow(), nullable=False)

    practice: Mapped["Practice"] = relationship(back_populates="portal_messages")

    __table_args__ = (
        Index("idx_messages_practice", "practice_id"),
        Index("idx_messages_thread", "thread_id"),
        Index("idx_messages_unread", "is_read", "practice_id"),
    )


class PortalNotification(Base):
    __tablename__ = "portal_notifications"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("users.id"), nullable=False)
    notification_type: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    link_url: Mapped[str | None] = mapped_column(String(500))
    is_read: Mapped[bool] = mapped_column(default=False)
    read_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=lambda: utcnow(), nullable=False)

    practice: Mapped["Practice"] = relationship(back_populates="portal_notifications")

    __table_args__ = (
        Index("idx_notifications_user", "user_id"),
        Index("idx_notifications_unread", "is_read", "user_id"),
    )


# ── Staff Management ───────────────────────────────────────────────────


class StaffAssignment(Base):
    __tablename__ = "staff_assignments"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("users.id"), nullable=False)
    role_in_practice: Mapped[str] = mapped_column(String(30), nullable=False)  # coder, biller, poster, denial_analyst, manager
    is_primary: Mapped[bool] = mapped_column(default=False)
    assigned_at: Mapped[datetime] = mapped_column(default=lambda: utcnow(), nullable=False)
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("users.id"))

    practice: Mapped["Practice"] = relationship(back_populates="staff_assignments")
    user: Mapped["User"] = relationship(back_populates="staff_assignments", foreign_keys=[user_id])

    __table_args__ = (
        UniqueConstraint("user_id", "practice_id", "role_in_practice", name="uq_staff_assignment"),
        Index("idx_assignments_user", "user_id"),
        Index("idx_assignments_practice", "practice_id"),
    )


class WorkQueueItem(Base, TimestampMixin):
    __tablename__ = "work_queue_items"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=False)
    queue_type: Mapped[str] = mapped_column(String(20), nullable=False)  # intake, coding, billing, posting, denial, follow_up
    item_type: Mapped[str] = mapped_column(String(30), nullable=False)  # charge_entry, coding_session, claim, payment_batch, denial
    item_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, nullable=False)
    priority: Mapped[int] = mapped_column(default=50)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, in_progress, completed, escalated
    due_date: Mapped[datetime | None]
    sla_breached: Mapped[bool] = mapped_column(default=False)
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    time_spent_seconds: Mapped[int | None]
    notes: Mapped[str | None] = mapped_column(Text)  # AI agent completion/escalation notes
    agent_trace: Mapped[list | None] = mapped_column(JSONB)  # step-by-step AI reasoning trace

    practice: Mapped["Practice"] = relationship(back_populates="work_queue_items")

    __table_args__ = (
        Index("idx_queue_type_status", "queue_type", "status"),
        Index("idx_queue_assigned", "assigned_to", "status"),
        Index("idx_queue_priority", "priority", "due_date"),
        Index("idx_queue_practice", "practice_id"),
        Index("idx_queue_sla", "sla_breached", postgresql_where=text("sla_breached = TRUE")),
    )


class StaffProductivity(Base):
    __tablename__ = "staff_productivity"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("users.id"), nullable=False)
    practice_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("practices.id"))  # NULL for aggregate
    date: Mapped[date] = mapped_column(Date, nullable=False)
    queue_type: Mapped[str] = mapped_column(String(20), nullable=False)

    items_completed: Mapped[int] = mapped_column(default=0)
    total_time_seconds: Mapped[int] = mapped_column(default=0)
    avg_time_per_item: Mapped[int] = mapped_column(default=0)
    errors_found: Mapped[int] = mapped_column(default=0)

    # Specific metrics
    claims_submitted: Mapped[int | None]
    claims_dollar_amount: Mapped[float | None]  # DECIMAL(14,2)
    payments_posted: Mapped[int | None]
    payments_dollar_amount: Mapped[float | None]  # DECIMAL(14,2)
    denials_worked: Mapped[int | None]
    denials_dollar_recovered: Mapped[float | None]  # DECIMAL(14,2)
    codes_reviewed: Mapped[int | None]
    coding_accuracy_pct: Mapped[float | None]  # DECIMAL(5,2)

    created_at: Mapped[datetime] = mapped_column(default=lambda: utcnow(), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "practice_id", "date", "queue_type", name="uq_productivity"),
        Index("idx_productivity_user", "user_id", "date"),
        Index("idx_productivity_practice", "practice_id", "date"),
    )


# ── Client Billing ─────────────────────────────────────────────────────


class ClientInvoice(Base, TimestampMixin):
    __tablename__ = "client_invoices"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("practices.id"), nullable=False)
    invoice_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    billing_period_start: Mapped[date] = mapped_column(Date, nullable=False)
    billing_period_end: Mapped[date] = mapped_column(Date, nullable=False)

    # Collection basis
    total_collections: Mapped[float] = mapped_column(nullable=False)  # DECIMAL(14,2)
    total_claims_submitted: Mapped[int | None]

    # Fee calculation
    fee_model_used: Mapped[str] = mapped_column(String(20), nullable=False)
    calculated_fee: Mapped[float] = mapped_column(nullable=False)  # DECIMAL(12,2)
    minimum_fee_applied: Mapped[bool] = mapped_column(default=False)
    adjustments: Mapped[float] = mapped_column(default=0)  # DECIMAL(12,2)
    total_due: Mapped[float] = mapped_column(nullable=False)  # DECIMAL(12,2)

    # Line items
    line_items: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Payment tracking
    status: Mapped[str] = mapped_column(String(20), default="draft")
    sent_at: Mapped[datetime | None]
    due_date: Mapped[date | None]
    paid_at: Mapped[datetime | None]
    paid_amount: Mapped[float | None]  # DECIMAL(12,2)
    payment_method: Mapped[str | None] = mapped_column(String(30))
    payment_reference: Mapped[str | None] = mapped_column(String(100))

    notes: Mapped[str | None] = mapped_column(Text)

    practice: Mapped["Practice"] = relationship(back_populates="client_invoices")

    __table_args__ = (
        Index("idx_invoices_practice", "practice_id"),
        Index("idx_invoices_status", "status"),
        Index("idx_invoices_period", "billing_period_start", "billing_period_end"),
    )


# ── Audit Log (not tenant-scoped, immutable) ────────────────────────────


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID)
    resource_detail: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(String(45))  # INET stored as string
    user_agent: Mapped[str | None] = mapped_column(Text)
    request_path: Mapped[str | None] = mapped_column(String(500))
    request_method: Mapped[str | None] = mapped_column(String(10))
    response_status: Mapped[int | None]
    phi_accessed: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: utcnow(), nullable=False)

    __table_args__ = (
        Index("idx_audit_user", "user_id"),
        Index("idx_audit_resource", "resource_type", "resource_id"),
                Index("idx_audit_created", "created_at"),
    )


# ── Error Intelligence ─────────────────────────────────────────────────────


class ErrorLog(Base, TimestampMixin):
    """
    Stores every unhandled application error along with its AI-generated analysis.
    Powers the Error Intelligence dashboard in the staff portal.
    """
    __tablename__ = "error_logs"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)

    # Error details
    error_type: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    stack_trace: Mapped[str | None] = mapped_column(Text)
    status_code: Mapped[int | None] = mapped_column(Integer)

    # Request context
    request_path: Mapped[str | None] = mapped_column(String(500))
    request_method: Mapped[str | None] = mapped_column(String(10))
    user_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID)

    # Sentry cross-reference
    sentry_event_id: Mapped[str | None] = mapped_column(String(100))

    # AI analysis
    severity: Mapped[str] = mapped_column(String(20), default="unknown")  # critical|high|medium|low|unknown
    analysis_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|analyzing|complete|failed
    ai_analysis: Mapped[dict | None] = mapped_column(JSONB)

    # Resolution
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID)

    # Deduplication
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)

    # Auto-patcher results
    patch_applied: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    patch_backup_path: Mapped[str | None] = mapped_column(Text)
    patch_diff: Mapped[str | None] = mapped_column(Text)
    patch_applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    patch_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("idx_error_logs_severity", "severity"),
        Index("idx_error_logs_resolved", "resolved"),
        Index("idx_error_logs_created", "created_at"),
        Index("idx_error_logs_type", "error_type"),
        Index("idx_error_logs_patch_applied", "patch_applied"),
    )


# ── Claim Forms (CMS-1500 / UB-04 assembled field sets) ──────────────────


class ClaimForm(Base, TimestampMixin):
    """Assembled, enriched, reviewable claim-form field set for a Claim.

    `fields` holds the full form payload (sections + diagnoses + service_lines)
    as produced by src.core.claim_forms; `edits` holds scrub validation; status
    is draft -> approved before submission.
    """
    __tablename__ = "claim_forms"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    claim_id: Mapped[uuid.UUID] = mapped_column(PG_UUID, ForeignKey("claims.id"), nullable=False)
    practice_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("practices.id"))
    form_type: Mapped[str] = mapped_column(String(10), nullable=False)  # cms1500 | ub04
    fields: Mapped[dict] = mapped_column(JSONB, nullable=False)
    edits: Mapped[list | None] = mapped_column(JSONB)
    enrichment: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")

    __table_args__ = (
        UniqueConstraint("claim_id", "form_type", name="uq_claim_forms_claim_formtype"),
        Index("idx_claim_forms_claim", "claim_id"),
    )


# ── Agent control plane (AI Assistant -> AI agents directives) ───────────


class AgentDirective(Base, TimestampMixin):
    """Runtime control for an AI agent, set by the AI Assistant / admins.

    agent_type '*' is the global default merged under each specific agent.
    confidence_threshold None -> use the platform settings default.
    instructions = standing natural-language policy injected into the agent's
    reasoning so assistant instructions are actually complied with.
    """
    __tablename__ = "agent_directives"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    agent_type: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    confidence_threshold: Mapped[float | None]
    auto_advance: Mapped[bool] = mapped_column(default=False, nullable=False)
    instructions: Mapped[str | None] = mapped_column(Text)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(PG_UUID)

class KnowledgeReference(TimestampMixin, Base):
    """Reference material (URLs / pasted text) the AI assistant + agents can cite.
    Retrieval is Postgres full-text search over `content`. Store non-PHI guidance only."""
    __tablename__ = "knowledge_references"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID, primary_key=True, default=uuid.uuid4)
    practice_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("practices.id"))  # null = global
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    url: Mapped[str | None] = mapped_column(String(1000))
    source_type: Mapped[str] = mapped_column(String(20), default="url")  # url | text
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    tags: Mapped[list | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | archived
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    added_by_id: Mapped[uuid.UUID | None] = mapped_column(PG_UUID, ForeignKey("users.id"))

    __table_args__ = (
        Index("ix_knowledge_practice", "practice_id"),
        Index("ix_knowledge_status", "status"),
    )
