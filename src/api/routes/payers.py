"""Payer intelligence routes: rules, fee schedules, policies."""
from fastapi import APIRouter
router = APIRouter()

@router.get("/")
async def list_payers():
    ...

@router.get("/{payer_id}")
async def get_payer(payer_id: str):
    ...

@router.get("/{payer_id}/rules")
async def get_payer_rules(payer_id: str):
    """Get all billing rules for a payer."""
    ...

@router.get("/{payer_id}/fee-schedule")
async def get_fee_schedule(payer_id: str):
    """Get contracted fee schedule rates."""
    ...

@router.get("/{payer_id}/policies")
async def search_payer_policies(payer_id: str, query: str):
    """Semantic search over payer policies."""
    ...
