"""Shared API schemas used across multiple modules."""

from typing import Generic, TypeVar
from pydantic import BaseModel


class MessageResponse(BaseModel):
    message: str


class IdResponse(BaseModel):
    id: str


T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard paginated response wrapper for list endpoints."""
    items: list[T]
    total: int
    page: int
    page_size: int