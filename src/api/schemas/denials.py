"""Schemas for denial management write endpoints."""

from uuid import UUID

from pydantic import BaseModel


class WriteOffRequest(BaseModel):
    reason: str


class AssignDenialRequest(BaseModel):
    user_id: UUID