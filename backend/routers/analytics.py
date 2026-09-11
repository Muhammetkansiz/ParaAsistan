# backend/routers/analytics.py
# ParaAsistan - Analitik & Raporlama Router Modülü

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from database import get_db
import models
import schemas
from auth import get_current_user
from services.recurring_service import process_recurring_transactions
from services import analytics_service

router = APIRouter(prefix="/api/analytics", tags=["Analiz"])

@router.get("/summary", response_model=schemas.SummaryResponse)
def get_financial_summary(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Kullanıcının toplam gelir, gider, bakiye ve tasarruf oranını döner."""
    process_recurring_transactions(db, current_user.id)
    summary_data = analytics_service.calculate_financial_summary(db, current_user.id)
    return schemas.SummaryResponse(**summary_data)


@router.get("/monthly-cashflow")
def get_monthly_cashflow(
    period: str = "6months",
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Seçilen döneme göre gelir ve gider akış grafiği verilerini döner."""
    return analytics_service.calculate_monthly_cashflow(db, current_user.id, period=period)


@router.get("/category-spending")
def get_category_spending(
    period: str = "month",
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Kategorilere göre harcama dağılımını ve yüzdelerini döner."""
    categories_data = analytics_service.calculate_category_spending(db, current_user.id, period=period)
    total_spent = sum(c["amount"] for c in categories_data) if categories_data else 0.0
    return {
        "period": period,
        "total_spent": round(total_spent, 2),
        "categories": categories_data
    }
