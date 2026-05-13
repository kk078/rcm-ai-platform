"""Schemas for claims, billing, and related write endpoints."""

from pydantic import BaseModel


class VoidRequest(BaseModel):
    reason: str | None = None


class BatchSubmitRequest(BaseModel):
    claim_ids: list[str]