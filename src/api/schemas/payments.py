"""Schemas for payment posting write endpoints."""

from uuid import UUID

from pydantic import BaseModel


class ManualMatchRequest(BaseModel):
    claim_id: UUID


class DisputeUnderpaymentRequest(BaseModel):
    expected_amount: float
    notes: str | None = None


class PostBatchRequest(BaseModel):
    auto_only: bool = True