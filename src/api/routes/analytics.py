"""Analytics and reporting routes."""
from fastapi import APIRouter
router = APIRouter()

@router.get("/dashboard")
async def get_dashboard():
    """Main dashboard KPIs: claims, payments, denials, revenue."""
    ...

@router.get("/revenue-cycle")
async def revenue_cycle_report():
    """Full revenue cycle metrics: days in AR, clean claim rate, denial rate."""
    ...

@router.get("/coding-accuracy")
async def coding_accuracy_report():
    """AI coding accuracy vs coder corrections."""
    ...

@router.get("/payer-performance")
async def payer_performance():
    """Payer comparison: payment speed, denial rates, underpayments."""
    ...

@router.get("/aging-report")
async def aging_report():
    """AR aging report: 0-30, 31-60, 61-90, 91-120, 120+ days."""
    ...
