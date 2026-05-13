"""Payer intelligence routes: rules, fee schedules, policies."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.session import get_db
from src.infrastructure.auth.middleware import get_current_user

router = APIRouter()


@router.get("/")
async def list_payers(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    return []


@router.get("/{payer_id}")
async def get_payer(
    payer_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    raise HTTPException(status_code=404, detail="Payer not found")


@router.get("/{payer_id}/rules")
async def get_payer_rules(
    payer_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get all billing rules for a payer."""
    return []


@router.get("/{payer_id}/fee-schedule")
async def get_fee_schedule(
    payer_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get contracted fee schedule rates."""
    return {}


@router.get("/{payer_id}/policies")
async def search_payer_policies(
    payer_id: str,
    query: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Semantic search over payer policies."""
    return []