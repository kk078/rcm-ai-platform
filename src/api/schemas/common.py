"""Shared API schemas used across multiple modules."""

from pydantic import BaseModel


class MessageResponse(BaseModel):
    message: str


class IdResponse(BaseModel):
    id: str