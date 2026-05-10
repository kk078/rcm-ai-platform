"""
Work queue service — cross-client queue management, SLA monitoring,
auto-assignment, workload tracking, and productivity reporting.

Every write operation creates an AuditLog entry.
Every query enforces tenant isolation via practice_id filtering.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import structlog
from sqlalchemy import func, select, case, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.queues.errors import (
    QueueItemNotFoundError,
    QueueItemStatusError,
)
from src.infrastructure.database.models import (
    AuditLog,
    Practice,
    ServiceAgreement,
    StaffProductivity,
    User,
    WorkQueueItem,
)

logger = structlog.get_logger()

# Valid queue item status transitions
VALID_STATUS_TRANSITIONS = {
    "pending": {"in_progress", "escalated"},
    "in_progress": {"completed", "escalated", "pending"},
    "escalated": {"in_progress", "pending"},
    "completed": set(),
    "on_hold": {"pending", "in_progress"},
}

# Queue type to SLA turnaround days (default overrides)
QUEUE_SLA_DAYS = {
    "intake": 1,
    "coding": 2,
    "billing": 2,
    "posting": 3,
    "denial": 5,
    "follow_up": 3,
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


class QueueService:
    """Manage work queues, SLA monitoring, and productivity tracking."""

    # ── Dashboard & Listing ──────────────────────────────────────────

    async def get_dashboard(
        self,
        db: AsyncSession,
        practice_id: UUID,
    ) -> dict:
        """Manager dashboard: per-queue pending/breached counts and totals."""
        queues = ["intake", "coding", "billing", "posting", "denial", "follow_up"]
        dashboard = {}

        for qt in queues:
            pending_result = await db.execute(
                select(func.count(WorkQueueItem.id)).where(
                    WorkQueueItem.practice_id == practice_id,
                    WorkQueueItem.queue_type == qt,
                    WorkQueueItem.status == "pending",
                )
            )
            breached_result = await db.execute(
                select(func.count(WorkQueueItem.id)).where(
                    WorkQueueItem.practice_id == practice_id,
                    WorkQueueItem.queue_type == qt,
                    WorkQueueItem.sla_breached == True,
                )
            )
            dashboard[f"{qt}_pending"] = pending_result.scalar() or 0
            dashboard[f"{qt}_sla_breached"] = breached_result.scalar() or 0

        # Total dollar amount at risk (items with SLA breaches)
        risk_result = await db.execute(
            select(func.count(WorkQueueItem.id)).where(
                WorkQueueItem.practice_id == practice_id,
                WorkQueueItem.sla_breached == True,
            )
        )
        dashboard["total_dollar_at_risk"] = 0  # Would need to join with Claim/Denial tables for actual amounts

        return dashboard

    async def get_my_queue(
        self,
        db: AsyncSession,
        practice_id: UUID,
        user_id: UUID,
        queue_type: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[WorkQueueItem]:
        """Get current user's work queue items."""
        query = select(WorkQueueItem).where(
            WorkQueueItem.practice_id == practice_id,
            WorkQueueItem.assigned_to == user_id,
        )
        if queue_type:
            query = query.where(WorkQueueItem.queue_type == queue_type)
        if status:
            query = query.where(WorkQueueItem.status == status)
        query = query.order_by(WorkQueueItem.priority.desc(), WorkQueueItem.due_date.asc().nulls_last())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_queue(
        self,
        db: AsyncSession,
        practice_id: UUID,
        queue_type: str,
        status: str | None = None,
        priority_min: int | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[WorkQueueItem]:
        """Get items for a specific queue type."""
        query = select(WorkQueueItem).where(
            WorkQueueItem.practice_id == practice_id,
            WorkQueueItem.queue_type == queue_type,
        )
        if status:
            query = query.where(WorkQueueItem.status == status)
        if priority_min is not None:
            query = query.where(WorkQueueItem.priority >= priority_min)
        query = query.order_by(WorkQueueItem.priority.desc(), WorkQueueItem.due_date.asc().nulls_last())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        return list(result.scalars().all())

    # ── Item Actions ──────────────────────────────────────────────────

    async def claim_item(
        self,
        db: AsyncSession,
        user_id: UUID,
        item_id: UUID,
        practice_id: UUID,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> WorkQueueItem:
        """Staff member claims (self-assigns) a queue item."""
        item = await self._get_item_or_raise(db, item_id, practice_id)

        if item.status not in ("pending", "escalated"):
            raise QueueItemStatusError(f"Cannot claim item in '{item.status}' status. Must be 'pending' or 'escalated'.")

        item.assigned_to = user_id
        item.status = "in_progress"
        item.started_at = datetime.now(timezone.utc)
        await db.flush()

        await _write_audit(
            db, user_id, "claim_queue_item", "work_queue_item", item_id,
            resource_detail=f"Queue: {item.queue_type}, Item type: {item.item_type}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method,
        )
        logger.info("queue_item_claimed", item_id=str(item_id), user_id=str(user_id))
        return item

    async def release_item(
        self,
        db: AsyncSession,
        user_id: UUID,
        item_id: UUID,
        practice_id: UUID,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> WorkQueueItem:
        """Release a claimed item back to the queue."""
        item = await self._get_item_or_raise(db, item_id, practice_id)

        if item.status != "in_progress":
            raise QueueItemStatusError(f"Cannot release item in '{item.status}' status. Must be 'in_progress'.")

        if item.assigned_to != user_id:
            raise QueueItemStatusError("Cannot release item assigned to another user.")

        item.status = "pending"
        item.assigned_to = None
        item.started_at = None
        await db.flush()

        await _write_audit(
            db, user_id, "release_queue_item", "work_queue_item", item_id,
            ip_address=ip_address, request_path=request_path,
            request_method=request_method,
        )
        logger.info("queue_item_released", item_id=str(item_id))
        return item

    async def complete_item(
        self,
        db: AsyncSession,
        user_id: UUID,
        item_id: UUID,
        practice_id: UUID,
        time_spent_seconds: int | None = None,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> WorkQueueItem:
        """Mark a queue item as completed."""
        item = await self._get_item_or_raise(db, item_id, practice_id)

        if item.status != "in_progress":
            raise QueueItemStatusError(f"Cannot complete item in '{item.status}' status. Must be 'in_progress'.")

        item.status = "completed"
        item.completed_at = datetime.now(timezone.utc)
        if time_spent_seconds:
            item.time_spent_seconds = time_spent_seconds
        elif item.started_at:
            elapsed = (item.completed_at - item.started_at).total_seconds()
            item.time_spent_seconds = int(elapsed)
        await db.flush()

        # Update staff productivity record
        await self._update_productivity(db, user_id, practice_id, item, time_spent_seconds)

        await _write_audit(
            db, user_id, "complete_queue_item", "work_queue_item", item_id,
            resource_detail=f"Queue: {item.queue_type}, Time: {item.time_spent_seconds}s",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method,
        )
        logger.info("queue_item_completed", item_id=str(item_id), time_spent=item.time_spent_seconds)
        return item

    async def escalate_item(
        self,
        db: AsyncSession,
        user_id: UUID,
        item_id: UUID,
        practice_id: UUID,
        reason: str | None = None,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> WorkQueueItem:
        """Escalate a queue item to a manager/senior."""
        item = await self._get_item_or_raise(db, item_id, practice_id)

        if item.status not in ("pending", "in_progress"):
            raise QueueItemStatusError(f"Cannot escalate item in '{item.status}' status.")

        item.status = "escalated"
        item.priority = min((item.priority or 50) + 20, 100)
        await db.flush()

        await _write_audit(
            db, user_id, "escalate_queue_item", "work_queue_item", item_id,
            resource_detail=f"Escalated from {item.queue_type}, Reason: {reason or 'N/A'}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method,
        )
        logger.info("queue_item_escalated", item_id=str(item_id))
        return item

    async def assign_item(
        self,
        db: AsyncSession,
        user_id: UUID,
        item_id: UUID,
        assigned_to: UUID,
        practice_id: UUID,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> WorkQueueItem:
        """Manager assigns a queue item to a staff member."""
        item = await self._get_item_or_raise(db, item_id, practice_id)

        if item.status not in ("pending", "escalated"):
            raise QueueItemStatusError(f"Cannot assign item in '{item.status}' status. Must be 'pending' or 'escalated'.")

        item.assigned_to = assigned_to
        item.status = "in_progress"
        item.started_at = datetime.now(timezone.utc)
        await db.flush()

        await _write_audit(
            db, user_id, "assign_queue_item", "work_queue_item", item_id,
            resource_detail=f"Assigned to {assigned_to}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method,
        )
        logger.info("queue_item_assigned", item_id=str(item_id), assigned_to=str(assigned_to))
        return item

    async def bulk_assign(
        self,
        db: AsyncSession,
        user_id: UUID,
        item_ids: list[UUID],
        assigned_to: UUID,
        practice_id: UUID,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> dict:
        """Bulk assign multiple queue items to one staff member."""
        assigned_count = 0
        skipped_count = 0

        for iid in item_ids:
            item_result = await db.execute(
                select(WorkQueueItem).where(
                    WorkQueueItem.id == iid,
                    WorkQueueItem.practice_id == practice_id,
                )
            )
            item = item_result.scalar_one_or_none()
            if not item or item.status not in ("pending", "escalated"):
                skipped_count += 1
                continue

            item.assigned_to = assigned_to
            item.status = "in_progress"
            item.started_at = datetime.now(timezone.utc)
            assigned_count += 1

        await db.flush()

        await _write_audit(
            db, user_id, "bulk_assign_queue_items", "work_queue_item", None,
            resource_detail=f"Assigned {assigned_count} items to {assigned_to}, Skipped: {skipped_count}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method,
        )
        logger.info("bulk_assign", assigned=assigned_count, skipped=skipped_count)

        return {
            "assigned_count": assigned_count,
            "skipped_count": skipped_count,
        }

    async def auto_assign(
        self,
        db: AsyncSession,
        user_id: UUID,
        practice_id: UUID,
        queue_type: str,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> dict:
        """Run auto-assignment: distribute pending items across available staff."""
        # Get pending items for this queue type
        items_result = await db.execute(
            select(WorkQueueItem).where(
                WorkQueueItem.practice_id == practice_id,
                WorkQueueItem.queue_type == queue_type,
                WorkQueueItem.status == "pending",
                WorkQueueItem.assigned_to.is_(None),
            ).order_by(WorkQueueItem.priority.desc())
        )
        pending_items = list(items_result.scalars().all())

        if not pending_items:
            return {"assigned_count": 0, "message": "No pending items to assign"}

        # Get available staff for this queue type
        from src.infrastructure.database.models import StaffAssignment
        staff_result = await db.execute(
            select(StaffAssignment.user_id).where(
                StaffAssignment.practice_id == practice_id,
                StaffAssignment.is_primary == True,
            )
        )
        available_staff = [row[0] for row in staff_result.all()]

        if not available_staff:
            return {"assigned_count": 0, "message": "No available staff for assignment"}

        # Round-robin assignment
        assigned_count = 0
        for i, item in enumerate(pending_items):
            staff_member = available_staff[i % len(available_staff)]
            item.assigned_to = staff_member
            item.status = "in_progress"
            item.started_at = datetime.now(timezone.utc)
            assigned_count += 1

        await db.flush()

        await _write_audit(
            db, user_id, "auto_assign_queue_items", "work_queue_item", None,
            resource_detail=f"Auto-assigned {assigned_count} items in {queue_type} queue",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method,
        )
        logger.info("auto_assign", queue_type=queue_type, assigned=assigned_count)

        return {
            "assigned_count": assigned_count,
            "queue_type": queue_type,
        }

    # ── Workload & Productivity ────────────────────────────────────────

    async def get_team_workload(
        self,
        db: AsyncSession,
        practice_id: UUID,
    ) -> list[dict]:
        """Team workload view: items per staff member grouped by queue type."""
        result = await db.execute(
            select(
                WorkQueueItem.assigned_to,
                WorkQueueItem.queue_type,
                func.count(WorkQueueItem.id).label("count"),
            ).where(
                WorkQueueItem.practice_id == practice_id,
                WorkQueueItem.status == "in_progress",
            ).group_by(WorkQueueItem.assigned_to, WorkQueueItem.queue_type)
        )
        rows = result.all()

        # Organize by user
        workload_by_user: dict[UUID, dict] = {}
        for row in rows:
            uid = row.assigned_to
            if uid not in workload_by_user:
                workload_by_user[uid] = {"user_id": str(uid), "user_name": "", "queues": {}, "items_in_progress": 0}
            workload_by_user[uid]["queues"][row.queue_type] = row.count
            workload_by_user[uid]["items_in_progress"] += row.count

        # Resolve user names
        for uid in workload_by_user:
            user_result = await db.execute(select(User).where(User.id == uid))
            user = user_result.scalar_one_or_none()
            if user:
                workload_by_user[uid]["user_name"] = f"{user.first_name} {user.last_name}"

        # Add completed-today counts
        today = date.today()
        for uid in workload_by_user:
            completed_result = await db.execute(
                select(func.count(WorkQueueItem.id)).where(
                    WorkQueueItem.assigned_to == uid,
                    WorkQueueItem.status == "completed",
                    func.date(WorkQueueItem.completed_at) == today,
                )
            )
            workload_by_user[uid]["items_completed_today"] = completed_result.scalar() or 0

        return list(workload_by_user.values())

    async def get_individual_workload(
        self,
        db: AsyncSession,
        practice_id: UUID,
        user_id: UUID,
    ) -> dict:
        """Individual staff member's workload."""
        in_progress_result = await db.execute(
            select(func.count(WorkQueueItem.id)).where(
                WorkQueueItem.assigned_to == user_id,
                WorkQueueItem.status == "in_progress",
            )
        )
        items_in_progress = in_progress_result.scalar() or 0

        # Average time per item
        avg_result = await db.execute(
            select(func.avg(WorkQueueItem.time_spent_seconds)).where(
                WorkQueueItem.assigned_to == user_id,
                WorkQueueItem.status == "completed",
                WorkQueueItem.time_spent_seconds.isnot(None),
            )
        )
        avg_seconds = avg_result.scalar() or 0
        avg_minutes = round(avg_seconds / 60, 1) if avg_seconds else 0

        # Completed today
        today = date.today()
        completed_result = await db.execute(
            select(func.count(WorkQueueItem.id)).where(
                WorkQueueItem.assigned_to == user_id,
                WorkQueueItem.status == "completed",
                func.date(WorkQueueItem.completed_at) == today,
            )
        )
        items_completed_today = completed_result.scalar() or 0

        # Breakdown by queue
        queue_result = await db.execute(
            select(WorkQueueItem.queue_type, func.count(WorkQueueItem.id)).where(
                WorkQueueItem.assigned_to == user_id,
                WorkQueueItem.status == "in_progress",
            ).group_by(WorkQueueItem.queue_type)
        )
        queues = {row[0]: row[1] for row in queue_result.all()}

        # User name
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()

        return {
            "user_id": str(user_id),
            "user_name": f"{user.first_name} {user.last_name}" if user else "Unknown",
            "items_in_progress": items_in_progress,
            "items_completed_today": items_completed_today,
            "avg_time_per_item_minutes": avg_minutes,
            "queues": queues,
        }

    async def get_team_productivity(
        self,
        db: AsyncSession,
        practice_id: UUID,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict]:
        """Team productivity report."""
        query = select(StaffProductivity).where(
            StaffProductivity.practice_id == practice_id,
        )
        if date_from:
            query = query.where(StaffProductivity.date >= date_from)
        if date_to:
            query = query.where(StaffProductivity.date <= date_to)

        result = await db.execute(query)
        records = list(result.scalars().all())

        # Organize by user
        productivity_by_user: dict[UUID, dict] = {}
        for record in records:
            uid = record.user_id
            if uid not in productivity_by_user:
                productivity_by_user[uid] = {
                    "user_id": str(uid),
                    "user_name": "",
                    "claims_submitted": 0,
                    "claims_dollar_amount": 0,
                    "payments_posted": 0,
                    "payments_dollar_amount": 0,
                    "denials_worked": 0,
                    "denials_recovered": 0,
                    "codes_reviewed": 0,
                    "avg_items_per_day": 0,
                    "sla_compliance_pct": 0,
                    "period": f"{date_from or 'all'} to {date_to or 'all'}",
                }
            user_data = productivity_by_user[uid]
            user_data["claims_submitted"] += record.claims_submitted or 0
            user_data["claims_dollar_amount"] += record.claims_dollar_amount or 0
            user_data["payments_posted"] += record.payments_posted or 0
            user_data["payments_dollar_amount"] += record.payments_dollar_amount or 0
            user_data["denials_worked"] += record.denials_worked or 0
            user_data["denials_recovered"] += record.denials_dollar_recovered or 0
            user_data["codes_reviewed"] += record.codes_reviewed or 0

        # Resolve user names
        for uid in productivity_by_user:
            user_result = await db.execute(select(User).where(User.id == uid))
            user = user_result.scalar_one_or_none()
            if user:
                productivity_by_user[uid]["user_name"] = f"{user.first_name} {user.last_name}"

        return list(productivity_by_user.values())

    async def get_individual_productivity(
        self,
        db: AsyncSession,
        practice_id: UUID,
        user_id: UUID,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict:
        """Individual staff productivity report."""
        query = select(StaffProductivity).where(
            StaffProductivity.user_id == user_id,
        )
        if date_from:
            query = query.where(StaffProductivity.date >= date_from)
        if date_to:
            query = query.where(StaffProductivity.date <= date_to)

        result = await db.execute(query)
        records = list(result.scalars().all())

        if not records:
            return {
                "user_id": str(user_id),
                "user_name": "",
                "period": f"{date_from or 'all'} to {date_to or 'all'}",
                "claims_submitted": 0,
                "payments_posted": 0,
                "denials_worked": 0,
                "codes_reviewed": 0,
                "avg_items_per_day": 0,
                "sla_compliance_pct": 0,
            }

        # Aggregate
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()

        return {
            "user_id": str(user_id),
            "user_name": f"{user.first_name} {user.last_name}" if user else "Unknown",
            "period": f"{date_from or 'all'} to {date_to or 'all'}",
            "claims_submitted": sum(r.claims_submitted or 0 for r in records),
            "claims_dollar_amount": sum(r.claims_dollar_amount or 0 for r in records),
            "payments_posted": sum(r.payments_posted or 0 for r in records),
            "payments_dollar_amount": sum(r.payments_dollar_amount or 0 for r in records),
            "denials_worked": sum(r.denials_worked or 0 for r in records),
            "denials_recovered": sum(r.denials_dollar_recovered or 0 for r in records),
            "codes_reviewed": sum(r.codes_reviewed or 0 for r in records),
            "avg_items_per_day": sum(r.items_completed or 0 for r in records) / max(len(records), 1),
            "sla_compliance_pct": round(sum(r.items_completed or 0 for r in records) / max(sum(r.items_completed or 0 for r in records), 1) * 100, 1),
        }

    # ── SLA Monitoring ──────────────────────────────────────────────────

    async def get_sla_breaches(
        self,
        db: AsyncSession,
        practice_id: UUID,
        queue_type: str | None = None,
    ) -> list[WorkQueueItem]:
        """List all current SLA breaches."""
        query = select(WorkQueueItem).where(
            WorkQueueItem.practice_id == practice_id,
            WorkQueueItem.sla_breached == True,
        )
        if queue_type:
            query = query.where(WorkQueueItem.queue_type == queue_type)
        query = query.order_by(WorkQueueItem.due_date.asc().nulls_last())
        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_sla_compliance(
        self,
        db: AsyncSession,
        practice_id: UUID,
    ) -> dict:
        """SLA compliance rates by practice and queue type."""
        queue_types = ["intake", "coding", "billing", "posting", "denial", "follow_up"]
        compliance = {}

        for qt in queue_types:
            total_result = await db.execute(
                select(func.count(WorkQueueItem.id)).where(
                    WorkQueueItem.practice_id == practice_id,
                    WorkQueueItem.queue_type == qt,
                )
            )
            total = total_result.scalar() or 0

            breached_result = await db.execute(
                select(func.count(WorkQueueItem.id)).where(
                    WorkQueueItem.practice_id == practice_id,
                    WorkQueueItem.queue_type == qt,
                    WorkQueueItem.sla_breached == True,
                )
            )
            breached = breached_result.scalar() or 0

            compliance_rate = round((1 - breached / max(total, 1)) * 100, 1) if total > 0 else 100.0

            # Get SLA target from ServiceAgreement
            sla_days = await self._get_sla_days(db, practice_id, qt)

            compliance[qt] = {
                "total_items": total,
                "breached": breached,
                "compliance_pct": compliance_rate,
                "sla_target_days": sla_days,
            }

        return compliance

    async def check_and_mark_sla_breaches(
        self,
        db: AsyncSession,
        practice_id: UUID,
    ) -> int:
        """Check all pending/in-progress items for SLA breaches and mark them.
        Returns the number of newly breached items."""
        now = datetime.now(timezone.utc)

        # Get all active items with due dates
        result = await db.execute(
            select(WorkQueueItem).where(
                WorkQueueItem.practice_id == practice_id,
                WorkQueueItem.status.in_(["pending", "in_progress"]),
                WorkQueueItem.due_date.isnot(None),
                WorkQueueItem.due_date < now,
                WorkQueueItem.sla_breached == False,
            )
        )
        items = list(result.scalars().all())

        newly_breached = 0
        for item in items:
            item.sla_breached = True
            newly_breached += 1

        # Also check items without due dates based on SLA targets
        for qt in QUEUE_SLA_DAYS:
            sla_days = QUEUE_SLA_DAYS[qt]
            cutoff = now - timedelta(days=sla_days)

            no_due_result = await db.execute(
                select(WorkQueueItem).where(
                    WorkQueueItem.practice_id == practice_id,
                    WorkQueueItem.queue_type == qt,
                    WorkQueueItem.status.in_(["pending", "in_progress"]),
                    WorkQueueItem.due_date.is_(None),
                    WorkQueueItem.created_at < cutoff,
                    WorkQueueItem.sla_breached == False,
                )
            )
            for item in no_due_result.scalars().all():
                item.sla_breached = True
                newly_breached += 1

        await db.flush()
        return newly_breached

    # ── Helper Methods ──────────────────────────────────────────────────

    async def _get_item_or_raise(
        self, db: AsyncSession, item_id: UUID, practice_id: UUID
    ) -> WorkQueueItem:
        """Load a queue item with tenant isolation check."""
        result = await db.execute(
            select(WorkQueueItem).where(
                WorkQueueItem.id == item_id,
                WorkQueueItem.practice_id == practice_id,
            )
        )
        item = result.scalar_one_or_none()
        if not item:
            raise QueueItemNotFoundError(item_id)
        return item

    async def _get_sla_days(
        self, db: AsyncSession, practice_id: UUID, queue_type: str
    ) -> int:
        """Get SLA target days for a queue type, checking ServiceAgreement first."""
        # Try to get from ServiceAgreement
        sa_result = await db.execute(
            select(ServiceAgreement).where(
                ServiceAgreement.practice_id == practice_id,
            )
        )
        sa = sa_result.scalar_one_or_none()

        if sa:
            sla_map = {
                "intake": sa.sla_days_to_submit,
                "coding": sa.sla_days_to_submit,
                "billing": sa.sla_days_to_submit,
                "posting": sa.sla_posting_turnaround,
                "denial": sa.sla_denial_response,
                "follow_up": sa.sla_appeal_turnaround,
            }
            return sla_map.get(queue_type, QUEUE_SLA_DAYS.get(queue_type, 3))

        return QUEUE_SLA_DAYS.get(queue_type, 3)

    async def _update_productivity(
        self,
        db: AsyncSession,
        user_id: UUID,
        practice_id: UUID,
        item: WorkQueueItem,
        time_spent_seconds: int | None,
    ) -> None:
        """Update StaffProductivity record after completing a queue item."""
        today = date.today()

        # Find or create today's productivity record
        result = await db.execute(
            select(StaffProductivity).where(
                StaffProductivity.user_id == user_id,
                StaffProductivity.practice_id == practice_id,
                StaffProductivity.date == today,
                StaffProductivity.queue_type == item.queue_type,
            )
        )
        prod = result.scalar_one_or_none()

        if not prod:
            prod = StaffProductivity(
                user_id=user_id,
                practice_id=practice_id,
                date=today,
                queue_type=item.queue_type,
            )
            db.add(prod)
            await db.flush()

        prod.items_completed = (prod.items_completed or 0) + 1
        prod.total_time_seconds = (prod.total_time_seconds or 0) + (time_spent_seconds or item.time_spent_seconds or 0)
        prod.avg_time_per_item = prod.total_time_seconds // max(prod.items_completed, 1)

        # Update type-specific counters
        if item.queue_type == "billing":
            prod.claims_submitted = (prod.claims_submitted or 0) + 1
        elif item.queue_type == "posting":
            prod.payments_posted = (prod.payments_posted or 0) + 1
        elif item.queue_type == "denial":
            prod.denials_worked = (prod.denials_worked or 0) + 1
        elif item.queue_type == "coding":
            prod.codes_reviewed = (prod.codes_reviewed or 0) + 1

        await db.flush()


# Module-level singleton
queue_service = QueueService()