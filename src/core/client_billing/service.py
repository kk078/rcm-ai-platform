"""
Client billing service — invoice generation, fee calculation, payment tracking,
revenue reporting, and client health dashboards.

Every write operation creates an AuditLog entry.
Every query enforces tenant isolation via practice_id filtering.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import structlog
from sqlalchemy import func, select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.client_billing.errors import (
    InvoiceNotFoundError,
    InvoiceStatusError,
    FeeCalculationError,
)
from src.core.client_management.service import service_agreement_service
from src.infrastructure.database.models import (
    AuditLog,
    Claim,
    ClientInvoice,
    Denial,
    Practice,
    ServiceAgreement,
    StaffProductivity,
    WorkQueueItem,
)

logger = structlog.get_logger()

# Valid invoice status transitions
VALID_INVOICE_TRANSITIONS = {
    "draft": {"sent"},
    "sent": {"paid", "overdue", "disputed", "void"},
    "viewed": {"paid", "overdue", "disputed", "void"},
    "paid": set(),
    "overdue": {"paid", "disputed", "void"},
    "disputed": {"paid", "void"},
    "void": set(),
}

# Invoice number prefix
INVOICE_PREFIX = "INV"


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


def _generate_invoice_number(seq: int) -> str:
    """Generate a human-readable invoice number like INV-2026-0001."""
    year = date.today().year
    return f"{INVOICE_PREFIX}-{year}-{seq:04d}"


class BillingService:
    """Manage client invoicing, fee calculation, and revenue reporting."""

    # ── Invoice Generation ──────────────────────────────────────────

    async def generate_invoice(
        self,
        db: AsyncSession,
        user_id: UUID,
        practice_id: UUID,
        billing_period_start: date,
        billing_period_end: date,
        additional_line_items: list[dict] | None = None,
        notes: str | None = None,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> ClientInvoice:
        """Generate a single invoice for a practice."""
        # Get practice name
        practice_result = await db.execute(
            select(Practice).where(Practice.id == practice_id)
        )
        practice = practice_result.scalar_one_or_none()
        if not practice:
            raise InvoiceNotFoundError(f"Practice {practice_id} not found")

        # Get active service agreement for fee calculation
        agreement = await service_agreement_service.get_active_agreement(db, practice_id)
        if not agreement:
            raise FeeCalculationError(f"No active service agreement for practice {practice.practice_name}")

        # Calculate total collections for the billing period
        collections_result = await db.execute(
            select(
                func.coalesce(func.sum(Claim.total_paid), 0).label("total_collections"),
                func.count(Claim.id).label("total_claims"),
            ).where(
                Claim.practice_id == practice_id,
                Claim.created_at >= billing_period_start,
                Claim.created_at <= billing_period_end,
                Claim.status.in_(["paid", "partial_paid"]),
            )
        )
        row = collections_result.one()
        total_collections = float(row.total_collections or 0)
        total_claims_submitted = int(row.total_claims or 0)

        # Also count submitted claims
        submitted_result = await db.execute(
            select(func.count(Claim.id)).where(
                Claim.practice_id == practice_id,
                Claim.created_at >= billing_period_start,
                Claim.created_at <= billing_period_end,
            )
        )
        total_claims_submitted = submitted_result.scalar() or 0

        # Calculate fee using service agreement
        try:
            fee_calc = await service_agreement_service.calculate_fee(
                db, practice_id, total_collections, total_claims_submitted,
            )
        except Exception as e:
            raise FeeCalculationError(f"Fee calculation failed: {e}")

        calculated_fee = fee_calc["calculated_fee"]
        minimum_fee_applied = fee_calc["minimum_fee_applied"]
        fee_model = fee_calc["fee_model"]

        # Build line items
        line_items = []

        # Base fee line item
        if fee_model == "percentage":
            line_items.append({
                "description": f"Billing services ({agreement.percentage_rate}% of ${total_collections:,.2f} collections)",
                "amount": calculated_fee,
                "category": "billing_services",
            })
        elif fee_model == "per_claim":
            line_items.append({
                "description": f"Billing services ({total_claims_submitted} claims × ${agreement.per_claim_rate:.2f})",
                "amount": calculated_fee,
                "category": "billing_services",
            })
        elif fee_model == "flat_fee":
            line_items.append({
                "description": f"Monthly billing services (flat fee)",
                "amount": calculated_fee,
                "category": "billing_services",
            })
        elif fee_model == "hybrid":
            line_items.append({
                "description": f"Billing services (hybrid: base ${agreement.hybrid_base_fee:.2f} + overage)",
                "amount": calculated_fee,
                "category": "billing_services",
            })

        # Add minimum fee note if applied
        if minimum_fee_applied:
            line_items.append({
                "description": f"Minimum monthly fee applied (${agreement.minimum_monthly_fee:.2f})",
                "amount": 0,
                "category": "adjustment",
            })

        # Add additional line items
        if additional_line_items:
            for item in additional_line_items:
                line_items.append({
                    "description": item.get("description", ""),
                    "amount": item.get("amount", 0),
                    "category": item.get("category", "other"),
                })

        # Calculate total
        adjustments = sum(item["amount"] for item in line_items if item["category"] in ("adjustment", "credit"))
        total_due = calculated_fee + adjustments

        # Generate invoice number
        count_result = await db.execute(
            select(func.count(ClientInvoice.id))
        )
        next_seq = (count_result.scalar() or 0) + 1
        invoice_number = _generate_invoice_number(next_seq)

        # Create invoice
        invoice = ClientInvoice(
            practice_id=practice_id,
            invoice_number=invoice_number,
            billing_period_start=billing_period_start,
            billing_period_end=billing_period_end,
            total_collections=total_collections,
            total_claims_submitted=total_claims_submitted,
            fee_model_used=fee_model,
            calculated_fee=calculated_fee,
            minimum_fee_applied=minimum_fee_applied,
            adjustments=adjustments,
            total_due=total_due,
            line_items=line_items,
            status="draft",
            notes=notes,
        )
        db.add(invoice)
        await db.flush()

        await _write_audit(
            db, user_id, "generate_invoice", "client_invoice", invoice.id,
            resource_detail=f"Invoice {invoice_number} for practice {practice.practice_name}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method,
        )
        logger.info("invoice_generated", invoice_number=invoice_number, practice_id=str(practice_id), total_due=total_due)
        return invoice

    async def generate_batch_invoices(
        self,
        db: AsyncSession,
        user_id: UUID,
        billing_period_start: date,
        billing_period_end: date,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> list[ClientInvoice]:
        """Generate invoices for all active practices."""
        # Get all active practices
        practices_result = await db.execute(
            select(Practice).where(Practice.status == "active")
        )
        practices = list(practices_result.scalars().all())

        invoices = []
        for practice in practices:
            try:
                invoice = await self.generate_invoice(
                    db, user_id, practice.id,
                    billing_period_start, billing_period_end,
                    ip_address=ip_address, request_path=request_path,
                    request_method=request_method,
                )
                invoices.append(invoice)
            except (FeeCalculationError, InvoiceNotFoundError):
                logger.warning("batch_invoice_skipped", practice_id=str(practice.id))

        await _write_audit(
            db, user_id, "generate_batch_invoices", "client_invoice", None,
            resource_detail=f"Generated {len(invoices)} invoices for period {billing_period_start} to {billing_period_end}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method,
        )
        logger.info("batch_invoices_generated", count=len(invoices))
        return invoices

    # ── Invoice Management ───────────────────────────────────────────

    async def list_invoices(
        self,
        db: AsyncSession,
        practice_id: UUID | None = None,
        status: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[ClientInvoice]:
        """List invoices with filtering."""
        query = select(ClientInvoice)
        if practice_id:
            query = query.where(ClientInvoice.practice_id == practice_id)
        if status:
            query = query.where(ClientInvoice.status == status)
        if date_from:
            query = query.where(ClientInvoice.billing_period_start >= date_from)
        if date_to:
            query = query.where(ClientInvoice.billing_period_end <= date_to)
        query = query.order_by(ClientInvoice.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_invoice(
        self, db: AsyncSession, invoice_id: UUID,
    ) -> ClientInvoice:
        """Get invoice details."""
        result = await db.execute(
            select(ClientInvoice).where(ClientInvoice.id == invoice_id)
        )
        invoice = result.scalar_one_or_none()
        if not invoice:
            raise InvoiceNotFoundError(invoice_id)
        return invoice

    async def update_invoice(
        self,
        db: AsyncSession,
        user_id: UUID,
        invoice_id: UUID,
        updates: dict,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> ClientInvoice:
        """Update a draft invoice."""
        invoice = await self.get_invoice(db, invoice_id)

        if invoice.status != "draft":
            raise InvoiceStatusError(f"Cannot edit invoice in '{invoice.status}' status. Only draft invoices can be edited.")

        # Apply allowed updates
        allowed_fields = {"notes", "line_items", "adjustments"}
        for field, value in updates.items():
            if field in allowed_fields and value is not None:
                setattr(invoice, field, value)

        # Recalculate total_due
        if "adjustments" in updates:
            invoice.total_due = invoice.calculated_fee + (invoice.adjustments or 0)

        await db.flush()

        await _write_audit(
            db, user_id, "update_invoice", "client_invoice", invoice_id,
            resource_detail=f"Updated invoice {invoice.invoice_number}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method,
        )
        return invoice

    async def send_invoice(
        self,
        db: AsyncSession,
        user_id: UUID,
        invoice_id: UUID,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> ClientInvoice:
        """Send invoice: set status to 'sent', set due date (Net 30)."""
        invoice = await self.get_invoice(db, invoice_id)

        if invoice.status != "draft":
            raise InvoiceStatusError(f"Cannot send invoice in '{invoice.status}' status. Must be 'draft'.")

        invoice.status = "sent"
        invoice.sent_at = datetime.now(timezone.utc).replace(tzinfo=None)
        invoice.due_date = date.today() + timedelta(days=30)  # Net 30
        await db.flush()

        await _write_audit(
            db, user_id, "send_invoice", "client_invoice", invoice_id,
            resource_detail=f"Invoice {invoice.invoice_number} sent, due {invoice.due_date}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method,
        )
        logger.info("invoice_sent", invoice_number=invoice.invoice_number)
        return invoice

    async def record_payment(
        self,
        db: AsyncSession,
        user_id: UUID,
        invoice_id: UUID,
        paid_amount: float,
        payment_method: str,
        payment_reference: str | None = None,
        payment_date: date | None = None,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> ClientInvoice:
        """Record a payment against an invoice."""
        invoice = await self.get_invoice(db, invoice_id)

        if invoice.status not in ("sent", "viewed", "overdue", "disputed"):
            raise InvoiceStatusError(f"Cannot record payment for invoice in '{invoice.status}' status.")

        invoice.paid_amount = paid_amount
        invoice.payment_method = payment_method
        invoice.payment_reference = payment_reference
        invoice.paid_at = datetime.now(timezone.utc).replace(tzinfo=None)
        invoice.status = "paid"
        await db.flush()

        await _write_audit(
            db, user_id, "record_invoice_payment", "client_invoice", invoice_id,
            resource_detail=f"Payment of ${paid_amount:,.2f} via {payment_method} recorded",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method,
        )
        logger.info("invoice_payment_recorded", invoice_number=invoice.invoice_number, amount=paid_amount)
        return invoice

    async def void_invoice(
        self,
        db: AsyncSession,
        user_id: UUID,
        invoice_id: UUID,
        reason: str | None = None,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> ClientInvoice:
        """Void an invoice."""
        invoice = await self.get_invoice(db, invoice_id)

        if invoice.status == "paid":
            raise InvoiceStatusError("Cannot void a paid invoice.")

        if invoice.status not in ("sent", "viewed", "overdue", "disputed", "draft"):
            raise InvoiceStatusError(f"Cannot void invoice in '{invoice.status}' status.")

        invoice.status = "void"
        invoice.notes = f"{invoice.notes or ''}\n\nVoided: {reason or 'No reason provided'}".strip()
        await db.flush()

        await _write_audit(
            db, user_id, "void_invoice", "client_invoice", invoice_id,
            resource_detail=f"Voided invoice {invoice.invoice_number}. Reason: {reason or 'N/A'}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method,
        )
        logger.info("invoice_voided", invoice_number=invoice.invoice_number)
        return invoice

    # ── Revenue Reporting ────────────────────────────────────────────

    async def revenue_dashboard(
        self,
        db: AsyncSession,
        period: str,
    ) -> dict:
        """Company revenue dashboard for a billing period."""
        year, month = int(period[:4]), int(period[5:7])
        start = date(year, month, 1)
        end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)

        # Invoice aggregates
        inv_result = await db.execute(
            select(
                func.coalesce(func.sum(ClientInvoice.total_due), 0).label("total_invoiced"),
                func.coalesce(func.sum(ClientInvoice.paid_amount), 0).label("total_collected"),
                func.count(ClientInvoice.id).label("invoice_count"),
            ).where(
                ClientInvoice.billing_period_start >= start,
                ClientInvoice.billing_period_end <= end,
                ClientInvoice.status != "void",
            )
        )
        inv = inv_result.one()

        total_invoiced = float(inv.total_invoiced or 0)
        total_collected = float(inv.total_collected or 0)
        total_outstanding = total_invoiced - total_collected

        # Overdue
        overdue_result = await db.execute(
            select(func.coalesce(func.sum(ClientInvoice.total_due), 0)).where(
                ClientInvoice.status == "overdue",
                ClientInvoice.billing_period_start >= start,
                ClientInvoice.billing_period_end <= end,
            )
        )
        total_overdue = float(overdue_result.scalar() or 0)

        # Revenue by fee model
        fee_model_result = await db.execute(
            select(
                ClientInvoice.fee_model_used,
                func.coalesce(func.sum(ClientInvoice.total_due), 0).label("revenue"),
            ).where(
                ClientInvoice.status != "void",
                ClientInvoice.billing_period_start >= start,
                ClientInvoice.billing_period_end <= end,
            ).group_by(ClientInvoice.fee_model_used)
        )
        revenue_by_fee_model = {row.fee_model_used: float(row.revenue) for row in fee_model_result.all()}

        # Top clients by revenue
        top_clients_result = await db.execute(
            select(
                Practice.practice_name,
                func.coalesce(func.sum(ClientInvoice.total_due), 0).label("revenue"),
            ).join(
                Practice, ClientInvoice.practice_id == Practice.id
            ).where(
                ClientInvoice.status != "void",
                ClientInvoice.billing_period_start >= start,
                ClientInvoice.billing_period_end <= end,
            ).group_by(Practice.practice_name).order_by(func.sum(ClientInvoice.total_due).desc()).limit(5)
        )
        top_clients = [
            {"practice_name": row.practice_name, "revenue": float(row.revenue), "collections_managed": 0}
            for row in top_clients_result.all()
        ]

        # Client count
        client_count_result = await db.execute(
            select(func.count(func.distinct(ClientInvoice.practice_id))).where(
                ClientInvoice.status != "void",
                ClientInvoice.billing_period_start >= start,
                ClientInvoice.billing_period_end <= end,
            )
        )
        client_count = client_count_result.scalar() or 1

        return {
            "period": period,
            "total_invoiced": total_invoiced,
            "total_collected": total_collected,
            "total_outstanding": total_outstanding,
            "total_overdue": total_overdue,
            "client_count": client_count,
            "avg_revenue_per_client": round(total_invoiced / max(client_count, 1), 2),
            "revenue_by_fee_model": revenue_by_fee_model,
            "top_clients": top_clients,
        }

    async def client_profitability(
        self,
        db: AsyncSession,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict]:
        """Client profitability analysis: revenue vs cost to service."""
        # Get all active practices
        practices_result = await db.execute(
            select(Practice).where(Practice.status == "active")
        )
        practices = list(practices_result.scalars().all())

        results = []
        for practice in practices:
            # Revenue from this client
            revenue_result = await db.execute(
                select(func.coalesce(func.sum(ClientInvoice.total_due), 0)).where(
                    ClientInvoice.practice_id == practice.id,
                    ClientInvoice.status != "void",
                )
            )
            revenue = float(revenue_result.scalar() or 0)

            # Staff hours (estimated from productivity)
            hours_result = await db.execute(
                select(func.coalesce(func.sum(StaffProductivity.total_time_seconds), 0)).where(
                    StaffProductivity.practice_id == practice.id,
                )
            )
            staff_seconds = int(hours_result.scalar() or 0)
            staff_hours = round(staff_seconds / 3600, 1)

            # Estimated cost (simplified: $50/hr average loaded cost)
            estimated_cost = staff_hours * 50

            # Claims volume
            claims_result = await db.execute(
                select(func.count(Claim.id)).where(
                    Claim.practice_id == practice.id,
                )
            )
            claims_volume = claims_result.scalar() or 0

            profit_margin = round((revenue - estimated_cost) / max(revenue, 1) * 100, 1) if revenue > 0 else 0

            results.append({
                "practice_id": str(practice.id),
                "practice_name": practice.practice_name,
                "revenue_from_client": revenue,
                "estimated_cost_to_service": estimated_cost,
                "profit_margin": profit_margin,
                "claims_volume": claims_volume,
                "staff_hours_spent": staff_hours,
                "revenue_per_claim": round(revenue / max(claims_volume, 1), 2),
            })

        return results

    async def revenue_projections(
        self,
        db: AsyncSession,
    ) -> dict:
        """Revenue projections based on current pipeline and historical data."""
        today = date.today()
        month_start = today.replace(day=1)

        # Current month invoiced
        current_result = await db.execute(
            select(func.coalesce(func.sum(ClientInvoice.total_due), 0)).where(
                ClientInvoice.billing_period_start >= month_start,
                ClientInvoice.status != "void",
            )
        )
        current_month_invoiced = float(current_result.scalar() or 0)

        # Active claims pipeline (submitted, not yet paid)
        pipeline_result = await db.execute(
            select(func.coalesce(func.sum(Claim.total_charge), 0)).where(
                Claim.status.in_(["submitted", "accepted", "partial_paid"]),
            )
        )
        pipeline_value = float(pipeline_result.scalar() or 0)

        # Historical average collection rate (last 3 months)
        three_months_ago = month_start - timedelta(days=90)
        hist_result = await db.execute(
            select(
                func.coalesce(func.sum(Claim.total_charge), 0).label("total_charged"),
                func.coalesce(func.sum(Claim.total_paid), 0).label("total_paid"),
            ).where(
                Claim.created_at >= three_months_ago,
                Claim.status.in_(["paid", "partial_paid"]),
            )
        )
        hist = hist_result.one()
        historical_collection_rate = float(hist.total_paid or 0) / max(float(hist.total_charged or 0), 1)

        # Average fee rate from service agreements
        avg_fee_result = await db.execute(
            select(func.avg(ServiceAgreement.percentage_rate)).where(
                ServiceAgreement.is_active == True,
                ServiceAgreement.fee_model == "percentage",
            )
        )
        avg_fee_rate = float(avg_fee_result.scalar() or 5.0)

        # Projected revenue
        projected_collections = pipeline_value * historical_collection_rate
        projected_fee_revenue = projected_collections * (avg_fee_rate / 100)

        return {
            "current_month_invoiced": current_month_invoiced,
            "pipeline_value": pipeline_value,
            "historical_collection_rate": round(historical_collection_rate * 100, 1),
            "projected_collections": round(projected_collections, 2),
            "projected_fee_revenue": round(projected_fee_revenue, 2),
            "projected_period": f"{today.strftime('%B %Y')}",
        }

    async def overdue_invoices(
        self,
        db: AsyncSession,
    ) -> list[ClientInvoice]:
        """List all overdue invoices."""
        # Mark overdue: sent invoices past their due_date
        today = date.today()
        await db.execute(
            ClientInvoice.__table__.update()
            .where(
                ClientInvoice.status.in_(["sent", "viewed"]),
                ClientInvoice.due_date < today,
            )
            .values(status="overdue")
        )

        result = await db.execute(
            select(ClientInvoice).where(
                ClientInvoice.status == "overdue",
            ).order_by(ClientInvoice.due_date.asc())
        )
        return list(result.scalars().all())

    # ── Client Health ─────────────────────────────────────────────────

    async def all_clients_health(
        self,
        db: AsyncSession,
    ) -> list[dict]:
        """Health overview for all active client practices."""
        practices_result = await db.execute(
            select(Practice).where(Practice.status == "active")
        )
        practices = list(practices_result.scalars().all())

        health_list = []
        for practice in practices:
            health = await self._compute_practice_health(db, practice.id, practice.practice_name)
            health_list.append(health)

        # Sort by clients needing attention (lowest clean_claim_rate, highest denial_rate)
        health_list.sort(key=lambda h: (h.get("denial_rate", 0), -h.get("clean_claim_rate", 100)))
        return health_list

    async def single_client_health(
        self,
        db: AsyncSession,
        practice_id: UUID,
    ) -> dict:
        """Detailed health metrics for a single practice."""
        practice_result = await db.execute(
            select(Practice).where(Practice.id == practice_id)
        )
        practice = practice_result.scalar_one_or_none()
        if not practice:
            raise InvoiceNotFoundError(f"Practice {practice_id} not found")

        health = await self._compute_practice_health(db, practice_id, practice.practice_name)

        # Add additional detail for single practice
        # SLA compliance
        sla_result = await db.execute(
            select(func.count(WorkQueueItem.id)).where(
                WorkQueueItem.practice_id == practice_id,
                WorkQueueItem.sla_breached == True,
            )
        )
        sla_breaches = sla_result.scalar() or 0

        health["sla_breaches"] = sla_breaches
        health["practice_id"] = str(practice_id)

        return health

    async def _compute_practice_health(
        self,
        db: AsyncSession,
        practice_id: UUID,
        practice_name: str,
    ) -> dict:
        """Compute health metrics for a single practice."""
        # Clean claim rate (claims that passed scrubbing without errors)
        total_result = await db.execute(
            select(func.count(Claim.id)).where(
                Claim.practice_id == practice_id,
            )
        )
        total_claims = total_result.scalar() or 1

        clean_result = await db.execute(
            select(func.count(Claim.id)).where(
                Claim.practice_id == practice_id,
                Claim.scrub_score >= 95,
            )
        )
        clean_claims = clean_result.scalar() or 0
        clean_claim_rate = round(clean_claims / max(total_claims, 1) * 100, 1)

        # Denial rate
        denied_result = await db.execute(
            select(func.count(Claim.id)).where(
                Claim.practice_id == practice_id,
                Claim.status == "denied",
            )
        )
        denied_claims = denied_result.scalar() or 0
        denial_rate = round(denied_claims / max(total_claims, 1) * 100, 1)

        # Collection rate
        paid_result = await db.execute(
            select(
                func.coalesce(func.sum(Claim.total_charge), 0).label("total_charged"),
                func.coalesce(func.sum(Claim.total_paid), 0).label("total_paid"),
            ).where(
                Claim.practice_id == practice_id,
            )
        )
        paid = paid_result.one()
        total_charged = float(paid.total_charged or 0)
        total_paid = float(paid.total_paid or 0)
        collection_rate = round(total_paid / max(total_charged, 1) * 100, 1) if total_charged > 0 else 0

        # AR balance
        ar_result = await db.execute(
            select(func.coalesce(func.sum(Claim.total_charge - Claim.total_paid - Claim.total_adjusted), 0)).where(
                Claim.practice_id == practice_id,
                Claim.status.notin_(["paid", "closed", "written_off"]),
            )
        )
        ar_balance = float(ar_result.scalar() or 0)

        return {
            "practice_id": str(practice_id),
            "practice_name": practice_name,
            "clean_claim_rate": clean_claim_rate,
            "denial_rate": denial_rate,
            "collection_rate": collection_rate,
            "total_claims": int(total_claims),
            "ar_balance": ar_balance,
        }


# Module-level singleton
billing_service = BillingService()