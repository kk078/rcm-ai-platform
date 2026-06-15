"""
Client Billing API Routes — Generate invoices for your provider clients,
track payments, and manage your revenue as a billing company.
Internal staff only (company_admin and billing_manager roles).
"""

from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.session import get_db
from src.infrastructure.database.models import ClientInvoice, Practice, ServiceAgreement, Claim
from src.infrastructure.auth.middleware import get_current_user
from src.api.schemas.common import PaginatedResponse

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────

class InvoiceStatus(str, Enum):
    DRAFT = "draft"
    SENT = "sent"
    VIEWED = "viewed"
    PAID = "paid"
    OVERDUE = "overdue"
    DISPUTED = "disputed"


class InvoiceLineItem(BaseModel):
    description: str
    amount: float
    category: str | None = None  # billing_services, coding, credentialing, adjustment, credit


class InvoiceCreate(BaseModel):
    practice_id: UUID
    billing_period_start: date
    billing_period_end: date
    additional_line_items: list[InvoiceLineItem] | None = None
    notes: str | None = None


class InvoiceResponse(BaseModel):
    id: UUID
    invoice_number: str
    practice_name: str
    billing_period: str
    total_collections: float
    fee_model: str
    calculated_fee: float
    adjustments: float
    total_due: float
    status: InvoiceStatus
    sent_at: datetime | None
    due_date: date | None
    paid_at: datetime | None
    paid_amount: float | None
    line_items: list[InvoiceLineItem]
    created_at: datetime

    model_config = {"from_attributes": True}


class VoidInvoiceRequest(BaseModel):
    reason: str


class BatchInvoiceRequest(BaseModel):
    billing_period_start: date
    billing_period_end: date


class InvoicePaymentRecord(BaseModel):
    paid_amount: float
    payment_method: str  # check, ach, credit_card, wire
    payment_reference: str | None = None
    payment_date: date


class CompanyRevenueReport(BaseModel):
    period: str
    total_invoiced: float
    total_collected: float
    total_outstanding: float
    total_overdue: float
    client_count: int
    avg_revenue_per_client: float
    revenue_by_fee_model: dict[str, float]
    top_clients: list[dict]  # [{practice_name, revenue, collections_managed}]


class ClientProfitability(BaseModel):
    practice_name: str
    revenue_from_client: float
    estimated_cost_to_service: float  # Based on staff time
    profit_margin: float
    claims_volume: int
    staff_hours_spent: float
    revenue_per_claim: float


# ── Helpers ──────────────────────────────────────────────────────

async def _build_invoice_response(invoice: ClientInvoice, db: AsyncSession) -> InvoiceResponse:
    """Build an InvoiceResponse from a ClientInvoice ORM object."""
    # Always query practice_name explicitly — avoid touching lazy-loaded relationships in async context
    practice_name = ""
    try:
        result = await db.execute(
            select(Practice.practice_name).where(Practice.id == invoice.practice_id)
        )
        practice_name = result.scalar_one_or_none() or ""
    except Exception:
        pass

    # Format billing period
    billing_period = f"{invoice.billing_period_start} to {invoice.billing_period_end}"

    # Parse line_items from JSONB
    line_items = []
    if invoice.line_items:
        if isinstance(invoice.line_items, list):
            line_items = [InvoiceLineItem(**item) if isinstance(item, dict) else item for item in invoice.line_items]

    return InvoiceResponse(
        id=invoice.id,
        invoice_number=invoice.invoice_number,
        practice_name=practice_name,
        billing_period=billing_period,
        total_collections=invoice.total_collections,
        fee_model=invoice.fee_model_used,
        calculated_fee=invoice.calculated_fee,
        adjustments=invoice.adjustments,
        total_due=invoice.total_due,
        status=InvoiceStatus(invoice.status),
        sent_at=invoice.sent_at,
        due_date=invoice.due_date,
        paid_at=invoice.paid_at,
        paid_amount=invoice.paid_amount,
        line_items=line_items,
        created_at=invoice.created_at,
    )


# ── Invoice Generation ───────────────────────────────────────────

@router.post("/invoices/generate", response_model=InvoiceResponse, status_code=201)
async def generate_invoice(
    invoice: InvoiceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Generate an invoice for a practice.

    Workflow:
    1. Pull the practice's service agreement (fee model, rates)
    2. Calculate total collections for the billing period
    3. Apply fee model:
       - Percentage: collections x rate
       - Per-claim: submitted claims x rate
       - Flat fee: monthly amount
       - Hybrid: base + overage percentage
    4. Apply minimum fee if applicable
    5. Add any additional line items (credentialing, special projects)
    6. Generate invoice number
    7. Return draft for review
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Look up the practice
    practice_result = await db.execute(select(Practice).where(Practice.id == invoice.practice_id))
    practice = practice_result.scalar_one_or_none()
    if not practice:
        raise HTTPException(status_code=404, detail="Practice not found")

    # Look up the service agreement for fee model
    agreement_result = await db.execute(
        select(ServiceAgreement).where(
            and_(
                ServiceAgreement.practice_id == invoice.practice_id,
                ServiceAgreement.is_active == True,
            )
        ).order_by(ServiceAgreement.effective_date.desc())
    )
    agreement = agreement_result.scalar_one_or_none()

    # Determine fee model
    fee_model_used = agreement.fee_model if agreement else "percentage"
    percentage_rate = agreement.percentage_rate if agreement else None
    per_claim_rate = agreement.per_claim_rate if agreement else None
    flat_fee_monthly = agreement.flat_fee_monthly if agreement else None

    # Calculate total collections for the billing period
    collections_result = await db.execute(
        select(func.coalesce(func.sum(Claim.total_paid), 0)).where(
            and_(
                Claim.practice_id == invoice.practice_id,
                Claim.adjudication_date >= invoice.billing_period_start,
                Claim.adjudication_date <= invoice.billing_period_end,
            )
        )
    )
    total_collections = float(collections_result.scalar() or 0)

    # Apply fee model
    calculated_fee = 0.0
    if fee_model_used == "percentage" and percentage_rate:
        calculated_fee = total_collections * (percentage_rate / 100)
    elif fee_model_used == "per_claim" and per_claim_rate:
        claims_count_result = await db.execute(
            select(func.count(Claim.id)).where(
                and_(
                    Claim.practice_id == invoice.practice_id,
                    Claim.submission_date >= invoice.billing_period_start,
                    Claim.submission_date <= invoice.billing_period_end,
                )
            )
        )
        claims_count = claims_count_result.scalar() or 0
        calculated_fee = claims_count * per_claim_rate
    elif fee_model_used == "flat_fee" and flat_fee_monthly:
        calculated_fee = flat_fee_monthly

    # Apply minimum fee
    minimum_fee = agreement.minimum_monthly_fee if agreement else None
    if minimum_fee and calculated_fee < minimum_fee:
        calculated_fee = minimum_fee

    # Build line items
    line_items = [
        {
            "description": f"Billing services ({fee_model_used})",
            "amount": calculated_fee,
            "category": "billing_services",
        }
    ]
    if invoice.additional_line_items:
        for item in invoice.additional_line_items:
            line_items.append(item.model_dump())

    total_due = calculated_fee + sum(item.get("amount", 0) for item in line_items[1:])
    adjustments = 0.0

    # Generate invoice number
    period_str = invoice.billing_period_start.strftime("%Y%m")
    count_result = await db.execute(
        select(func.count(ClientInvoice.id)).where(
            ClientInvoice.invoice_number.like(f"INV-{period_str}-%")
        )
    )
    count = (count_result.scalar() or 0) + 1
    invoice_number = f"INV-{period_str}-{count:04d}"

    # Create the invoice in DB
    db_invoice = ClientInvoice(
        id=uuid4(),
        practice_id=invoice.practice_id,
        invoice_number=invoice_number,
        billing_period_start=invoice.billing_period_start,
        billing_period_end=invoice.billing_period_end,
        total_collections=total_collections,
        fee_model_used=fee_model_used,
        calculated_fee=calculated_fee,
        adjustments=adjustments,
        total_due=total_due,
        line_items=line_items,
        status="draft",
        notes=invoice.notes,
    )
    db.add(db_invoice)
    await db.flush()

    return await _build_invoice_response(db_invoice, db)


@router.post("/invoices/generate-batch")
async def generate_all_invoices(
    body: BatchInvoiceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Generate invoices for ALL active practices for a billing period.
    Returns a list of generated invoices for review before sending.
    """
    # Get all active practices
    result = await db.execute(
        select(Practice).where(Practice.status == "active")
    )
    practices = result.scalars().all()

    generated = []
    for practice in practices:
        # Check if invoice already exists for this period
        existing = await db.execute(
            select(ClientInvoice).where(
                and_(
                    ClientInvoice.practice_id == practice.id,
                    ClientInvoice.billing_period_start == body.billing_period_start,
                    ClientInvoice.billing_period_end == body.billing_period_end,
                )
            )
        )
        if existing.scalar_one_or_none():
            continue

        generated.append({"practice_id": str(practice.id), "practice_name": practice.practice_name})

    return {"message": "Batch invoice generation initiated", "practices": generated, "count": len(generated)}


# ── Invoice Management ───────────────────────────────────────────

@router.get("/invoices", response_model=PaginatedResponse[InvoiceResponse])
async def list_invoices(
    practice_id: UUID | None = None,
    status: InvoiceStatus | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List invoices with filtering."""
    conditions = []
    if practice_id:
        conditions.append(ClientInvoice.practice_id == practice_id)
    if status:
        conditions.append(ClientInvoice.status == status.value)
    if date_from:
        conditions.append(ClientInvoice.billing_period_start >= date_from)
    if date_to:
        conditions.append(ClientInvoice.billing_period_end <= date_to)

    where_clause = and_(*conditions) if conditions else True

    # Total count with the same filters
    count_result = await db.execute(
        select(func.count(ClientInvoice.id)).where(where_clause)
    )
    total = count_result.scalar() or 0

    offset = (page - 1) * page_size
    result = await db.execute(
        select(ClientInvoice)
        .where(where_clause)
        .order_by(ClientInvoice.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    invoices = result.scalars().all()

    responses = []
    for inv in invoices:
        resp = await _build_invoice_response(inv, db)
        responses.append(resp)
    return {"items": responses, "total": total, "page": page, "page_size": page_size}


@router.get("/invoices/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get invoice details with line items."""
    result = await db.execute(select(ClientInvoice).where(ClientInvoice.id == invoice_id))
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    return await _build_invoice_response(invoice, db)


@router.patch("/invoices/{invoice_id}")
async def update_invoice(
    invoice_id: UUID,
    updates: InvoiceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Edit a draft invoice before sending (add/remove line items, adjust amounts)."""
    result = await db.execute(select(ClientInvoice).where(ClientInvoice.id == invoice_id))
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if invoice.status != "draft":
        raise HTTPException(status_code=400, detail="Only draft invoices can be edited")

    # Update fields
    invoice.billing_period_start = updates.billing_period_start
    invoice.billing_period_end = updates.billing_period_end
    if updates.notes:
        invoice.notes = updates.notes
    if updates.additional_line_items:
        existing_items = invoice.line_items or []
        if isinstance(existing_items, list):
            existing_items.extend([item.model_dump() for item in updates.additional_line_items])
            invoice.line_items = existing_items

    await db.flush()

    return await _build_invoice_response(invoice, db)


@router.post("/invoices/{invoice_id}/send")
async def send_invoice(
    invoice_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Send invoice to the practice:
    1. Generate PDF
    2. Make available in provider portal
    3. Send email notification to practice admin
    4. Set due date (typically Net 30)
    5. Update status to 'sent'
    """
    result = await db.execute(select(ClientInvoice).where(ClientInvoice.id == invoice_id))
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if invoice.status != "draft":
        raise HTTPException(status_code=400, detail="Only draft invoices can be sent")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    from datetime import timedelta
    invoice.status = "sent"
    invoice.sent_at = now
    invoice.due_date = (now + timedelta(days=30)).date()

    await db.flush()

    return {"message": "Invoice sent", "invoice_id": str(invoice_id), "due_date": invoice.due_date.isoformat()}


@router.post("/invoices/{invoice_id}/record-payment")
async def record_payment(
    invoice_id: UUID,
    payment: InvoicePaymentRecord,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Record a payment received from a practice against an invoice."""
    result = await db.execute(select(ClientInvoice).where(ClientInvoice.id == invoice_id))
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    invoice.paid_amount = payment.paid_amount
    invoice.payment_method = payment.payment_method
    invoice.payment_reference = payment.payment_reference
    invoice.paid_at = now

    # Check if fully paid
    if payment.paid_amount >= invoice.total_due:
        invoice.status = "paid"
    else:
        invoice.status = "viewed"  # Partial payment

    await db.flush()

    return await _build_invoice_response(invoice, db)


@router.post("/invoices/{invoice_id}/void")
async def void_invoice(
    invoice_id: UUID,
    body: VoidInvoiceRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Void a sent invoice (e.g., billing error)."""
    result = await db.execute(select(ClientInvoice).where(ClientInvoice.id == invoice_id))
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if invoice.status == "paid":
        raise HTTPException(status_code=400, detail="Cannot void a paid invoice")

    invoice.status = "disputed"
    invoice.notes = (invoice.notes or "") + f"\nVoided: {body.reason}"

    await db.flush()

    return {"message": "Invoice voided", "invoice_id": str(invoice_id)}


@router.get("/invoices/{invoice_id}/download-pdf")
async def download_invoice_pdf(
    invoice_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Generate and download invoice as PDF."""
    result = await db.execute(select(ClientInvoice).where(ClientInvoice.id == invoice_id))
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    return {"message": "PDF generation not yet available"}


@router.get("/invoices/{invoice_id}/lines")
async def get_invoice_lines(
    invoice_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get line items for an invoice."""
    result = await db.execute(select(ClientInvoice).where(ClientInvoice.id == invoice_id))
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    return invoice.line_items or []


# ── Company Revenue Reporting ────────────────────────────────────

@router.get("/revenue/dashboard", response_model=CompanyRevenueReport)
async def revenue_dashboard(
    period: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Your company's revenue dashboard:
    - Total invoiced, collected, outstanding, overdue
    - Revenue by fee model
    - Top clients by revenue
    When no period is given (or the period has no data), returns all-time totals.
    """
    if period is None:
        period = "all"

    # Build optional date filter — only applied when a specific YYYY-MM is requested
    date_conditions: list = []
    if period != "all":
        try:
            year, month = period.split("-")
            period_start = date(int(year), int(month), 1)
            period_end = date(int(year) + 1, 1, 1) if int(month) == 12 else date(int(year), int(month) + 1, 1)
            date_conditions = [
                ClientInvoice.billing_period_start >= period_start,
                ClientInvoice.billing_period_start < period_end,
            ]
        except Exception:
            pass  # fall back to all-time

    def _where(*extra):
        conds = list(date_conditions) + list(extra)
        return and_(*conds) if conds else True

    # Total invoiced
    invoiced_q = await db.execute(
        select(func.coalesce(func.sum(ClientInvoice.total_due), 0)).where(_where())
    )
    total_invoiced = float(invoiced_q.scalar() or 0)

    # Total collected
    collected_q = await db.execute(
        select(func.coalesce(func.sum(ClientInvoice.paid_amount), 0)).where(
            _where(ClientInvoice.status == "paid")
        )
    )
    total_collected = float(collected_q.scalar() or 0)

    # Outstanding
    outstanding_q = await db.execute(
        select(func.coalesce(func.sum(ClientInvoice.total_due - func.coalesce(ClientInvoice.paid_amount, 0)), 0)).where(
            _where(ClientInvoice.status.in_(["sent", "viewed"]))
        )
    )
    total_outstanding = float(outstanding_q.scalar() or 0)

    # Overdue
    overdue_q = await db.execute(
        select(func.coalesce(func.sum(ClientInvoice.total_due), 0)).where(
            _where(ClientInvoice.status == "overdue")
        )
    )
    total_overdue = float(overdue_q.scalar() or 0)

    # Client count
    client_count_q = await db.execute(
        select(func.count(func.distinct(ClientInvoice.practice_id))).where(_where())
    )
    client_count = client_count_q.scalar() or 0

    avg_revenue_per_client = total_invoiced / client_count if client_count else 0.0

    # Revenue by fee model
    fee_model_q = await db.execute(
        select(ClientInvoice.fee_model_used, func.coalesce(func.sum(ClientInvoice.total_due), 0)).where(
            _where()
        ).group_by(ClientInvoice.fee_model_used)
    )
    revenue_by_fee_model = {row[0]: float(row[1]) for row in fee_model_q.all()}

    # Top clients
    top_clients_q = await db.execute(
        select(
            Practice.practice_name,
            func.coalesce(func.sum(ClientInvoice.total_due), 0).label("revenue"),
            func.coalesce(func.sum(ClientInvoice.total_collections), 0).label("collections"),
        )
        .join(Practice, ClientInvoice.practice_id == Practice.id)
        .where(_where())
        .group_by(Practice.practice_name)
        .order_by(func.sum(ClientInvoice.total_due).desc())
        .limit(10)
    )
    top_clients = [
        {
            "practice_name": row[0],
            "revenue": float(row[1]),
            "collections_managed": float(row[2]),
        }
        for row in top_clients_q.all()
    ]

    return CompanyRevenueReport(
        period=period,
        total_invoiced=total_invoiced,
        total_collected=total_collected,
        total_outstanding=total_outstanding,
        total_overdue=total_overdue,
        client_count=client_count,
        avg_revenue_per_client=round(avg_revenue_per_client, 2),
        revenue_by_fee_model=revenue_by_fee_model,
        top_clients=top_clients,
    )


@router.get("/revenue/profitability", response_model=list[ClientProfitability])
async def client_profitability_report(
    date_from: date | None = None,
    date_to: date | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Client profitability analysis:
    - Revenue from each client vs estimated cost to service
    - Based on staff hours logged against each practice
    - Identifies unprofitable clients
    """
    # Query practices with their invoice totals
    result = await db.execute(
        select(Practice).where(Practice.status == "active")
    )
    practices = result.scalars().all()

    profitability_list = []
    for practice in practices:
        # Get total revenue from invoices for this practice
        conditions = [ClientInvoice.practice_id == practice.id]
        if date_from:
            conditions.append(ClientInvoice.billing_period_start >= date_from)
        if date_to:
            conditions.append(ClientInvoice.billing_period_end <= date_to)

        revenue_q = await db.execute(
            select(func.coalesce(func.sum(ClientInvoice.total_due), 0)).where(and_(*conditions))
        )
        revenue = float(revenue_q.scalar() or 0)

        claims_q = await db.execute(
            select(func.count(Claim.id)).where(Claim.practice_id == practice.id)
        )
        claims_volume = claims_q.scalar() or 0

        profitability_list.append(ClientProfitability(
            practice_name=practice.practice_name,
            revenue_from_client=revenue,
            estimated_cost_to_service=0.0,
            profit_margin=0.0,
            claims_volume=claims_volume,
            staff_hours_spent=0.0,
            revenue_per_claim=round(revenue / claims_volume, 2) if claims_volume else 0.0,
        ))

    return profitability_list


@router.get("/revenue/projections")
async def revenue_projections(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Revenue projections based on:
    - Current pipeline (charges submitted, expected collection rates)
    - Historical collection patterns per practice
    - Seasonal trends
    """
    return {}


@router.get("/revenue/overdue")
async def overdue_invoices(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List all overdue invoices across practices with aging."""
    result = await db.execute(
        select(ClientInvoice).where(
            ClientInvoice.status.in_(["sent", "viewed", "overdue"])
        ).order_by(ClientInvoice.due_date.asc())
    )
    invoices = result.scalars().all()

    overdue_list = []
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for inv in invoices:
        days_overdue = 0
        if inv.due_date:
            days_overdue = (now.date() - inv.due_date).days

        practice_name = ""
        try:
            pn_r = await db.execute(select(Practice.practice_name).where(Practice.id == inv.practice_id))
            practice_name = pn_r.scalar_one_or_none() or ""
        except Exception:
            pass

        overdue_list.append({
            "id": str(inv.id),
            "invoice_number": inv.invoice_number,
            "practice_name": practice_name,
            "total_due": inv.total_due,
            "paid_amount": inv.paid_amount or 0,
            "balance": inv.total_due - (inv.paid_amount or 0),
            "due_date": inv.due_date.isoformat() if inv.due_date else None,
            "days_overdue": max(days_overdue, 0),
            "status": inv.status,
        })

    return overdue_list


# ── Client Performance Summary ───────────────────────────────────

@router.get("/client-health")
async def all_clients_health_overview(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    At-a-glance health of all client practices:
    - Clean claim rate vs SLA target
    - Denial rate trend (improving/worsening)
    - Days in AR vs benchmark
    - Collection rate
    - Any SLA breaches
    Sorted by: clients needing attention first.
    """
    result = await db.execute(
        select(Practice).where(Practice.status == "active")
    )
    practices = result.scalars().all()

    health_list = []
    for practice in practices:
        # Get basic claim stats for this practice
        total_q = await db.execute(
            select(func.count(Claim.id)).where(Claim.practice_id == practice.id)
        )
        total_claims = total_q.scalar() or 0

        denied_q = await db.execute(
            select(func.count(Claim.id)).where(
                and_(Claim.practice_id == practice.id, Claim.status == "denied")
            )
        )
        denied_claims = denied_q.scalar() or 0

        paid_q = await db.execute(
            select(func.count(Claim.id)).where(
                and_(Claim.practice_id == practice.id, Claim.status == "paid")
            )
        )
        paid_claims = paid_q.scalar() or 0

        denial_rate = round(denied_claims / total_claims, 4) if total_claims else 0.0
        clean_claim_rate = round((total_claims - denied_claims) / total_claims, 4) if total_claims else 1.0

        health_list.append({
            "practice_id": str(practice.id),
            "practice_name": practice.practice_name,
            "total_claims": total_claims,
            "denied_claims": denied_claims,
            "paid_claims": paid_claims,
            "denial_rate": denial_rate,
            "clean_claim_rate": clean_claim_rate,
        })

    # Sort by denial rate descending (clients needing attention first)
    health_list.sort(key=lambda x: x["denial_rate"], reverse=True)
    return health_list


@router.get("/client-health/{practice_id}")
async def single_client_health(
    practice_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Detailed health metrics for a single practice."""
    result = await db.execute(select(Practice).where(Practice.id == practice_id))
    practice = result.scalar_one_or_none()
    if not practice:
        raise HTTPException(status_code=404, detail="Practice not found")

    # Get detailed claim stats
    total_q = await db.execute(
        select(func.count(Claim.id)).where(Claim.practice_id == practice_id)
    )
    total_claims = total_q.scalar() or 0

    denied_q = await db.execute(
        select(func.count(Claim.id)).where(
            and_(Claim.practice_id == practice_id, Claim.status == "denied")
        )
    )
    denied_claims = denied_q.scalar() or 0

    paid_q = await db.execute(
        select(func.count(Claim.id)).where(
            and_(Claim.practice_id == practice_id, Claim.status == "paid")
        )
    )
    paid_claims = paid_q.scalar() or 0

    # Total collected amount
    collected_q = await db.execute(
        select(func.coalesce(func.sum(Claim.total_paid), 0)).where(Claim.practice_id == practice_id)
    )
    total_collected = float(collected_q.scalar() or 0)

    # Total charged amount
    charged_q = await db.execute(
        select(func.coalesce(func.sum(Claim.total_charge), 0)).where(Claim.practice_id == practice_id)
    )
    total_charged = float(charged_q.scalar() or 0)

    collection_rate = round(total_collected / total_charged, 4) if total_charged else 0.0

    return {
        "practice_id": str(practice_id),
        "practice_name": practice.practice_name,
        "total_claims": total_claims,
        "denied_claims": denied_claims,
        "paid_claims": paid_claims,
        "total_charged": total_charged,
        "total_collected": total_collected,
        "collection_rate": collection_rate,
        "denial_rate": round(denied_claims / total_claims, 4) if total_claims else 0.0,
        "clean_claim_rate": round((total_claims - denied_claims) / total_claims, 4) if total_claims else 1.0,
    }