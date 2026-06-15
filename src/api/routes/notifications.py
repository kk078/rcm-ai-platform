"""Notification management routes."""
from __future__ import annotations
import uuid
from typing import Any
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from src.infrastructure.database.session import get_db
from src.infrastructure.auth.middleware import get_current_user
from src.infrastructure.database.models import NotificationLog, NotificationRule, User

router = APIRouter(prefix="/notifications", tags=["Notifications"])


class NotificationRuleCreate(BaseModel):
    event_type: str
    channels: list[str]
    role_filter: list[str] | None = None
    threshold_hours: int | None = None
    template_subject: str | None = None
    template_body: str | None = None
    is_active: bool = True


class NotificationLogResponse(BaseModel):
    id: uuid.UUID
    event_type: str
    channel: str
    recipient: str | None
    subject: str | None
    status: str
    entity_type: str | None
    entity_id: uuid.UUID | None
    error_message: str | None
    created_at: Any

    class Config:
        from_attributes = True


class NotificationRuleResponse(BaseModel):
    id: uuid.UUID
    event_type: str
    channels: list[str]
    role_filter: list[str] | None
    threshold_hours: int | None
    is_active: bool
    template_subject: str | None
    template_body: str | None

    class Config:
        from_attributes = True


@router.get("/log", response_model=list[NotificationLogResponse])
async def get_notification_log(
    event_type: str | None = None,
    channel: str | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get notification history for the practice."""
    filters = [NotificationLog.practice_id == current_user.get("practice_id")]
    if event_type:
        filters.append(NotificationLog.event_type == event_type)
    if channel:
        filters.append(NotificationLog.channel == channel)
    result = await db.execute(
        select(NotificationLog).where(*filters)
        .order_by(desc(NotificationLog.created_at))
        .offset(skip).limit(limit)
    )
    return [NotificationLogResponse.model_validate(n) for n in result.scalars().all()]


@router.get("/rules", response_model=list[NotificationRuleResponse])
async def get_notification_rules(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(NotificationRule).where(
            (NotificationRule.practice_id == current_user.get("practice_id")) |
            (NotificationRule.practice_id == None)
        )
    )
    return [NotificationRuleResponse.model_validate(r) for r in result.scalars().all()]


@router.post("/rules", response_model=NotificationRuleResponse, status_code=201)
async def create_notification_rule(
    data: NotificationRuleCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rule = NotificationRule(
        practice_id=current_user.get("practice_id"),
        **data.model_dump(),
    )
    db.add(rule)
    await db.flush()
    return NotificationRuleResponse.model_validate(rule)
