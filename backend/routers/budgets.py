# backend/routers/budgets.py
# ParaAsistan - Bütçe Yönetimi Router Modülü

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from typing import List
import datetime
from database import get_db
import models
import schemas
from auth import get_current_user

router = APIRouter(prefix="/api/budgets", tags=["Bütçeler"])

@router.post("", response_model=schemas.BudgetProgressResponse)
def create_or_update_budget(
    budget: schemas.BudgetCreate, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Kullanıcı için yeni bir kategori bütçesi oluşturur veya mevcut limiti günceller."""
    existing_budget = db.query(models.Budget).filter(
        models.Budget.category == budget.category,
        models.Budget.user_id == current_user.id
    ).first()

    if existing_budget:
        existing_budget.monthly_limit = budget.monthly_limit
        db.commit()
        db.refresh(existing_budget)
        db_budget = existing_budget
    else:
        db_budget = models.Budget(
            user_id=current_user.id,
            category=budget.category,
            monthly_limit=budget.monthly_limit,
            month=budget.month
        )
        db.add(db_budget)
        db.commit()
        db.refresh(db_budget)

    now = datetime.datetime.now()
    spent = db.query(func.sum(models.Transaction.amount)).filter(
        models.Transaction.type == "expense",
        models.Transaction.user_id == current_user.id,
        models.Transaction.category == db_budget.category,
        extract('year', models.Transaction.date) == now.year, 
        extract('month', models.Transaction.date) == now.month
    ).scalar() or 0.0

    rem = db_budget.monthly_limit - spent
    pct = round((spent / db_budget.monthly_limit) * 100, 1) if db_budget.monthly_limit > 0 else 0.0

    return schemas.BudgetProgressResponse(
        id=db_budget.id,
        category=db_budget.category,
        monthly_limit=round(db_budget.monthly_limit, 2),
        spent=round(spent, 2),
        remaining=round(rem, 2),
        percentage=pct,
        status="exceeded" if spent > db_budget.monthly_limit else ("warning" if pct >= 85 else "on_track")
    )


@router.get("", response_model=List[schemas.BudgetProgressResponse])
def get_budgets_progress(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Kullanıcının tüm bütçelerini ve anlık harcama durumlarını listeler."""
    budgets = db.query(models.Budget).filter(models.Budget.user_id == current_user.id).all()
    if not budgets:
        return []

    now = datetime.datetime.now()
    result = []
    for b in budgets:
        spent = db.query(func.sum(models.Transaction.amount)).filter(
            models.Transaction.type == "expense",
            models.Transaction.user_id == current_user.id,
            models.Transaction.category == b.category,
            extract('year', models.Transaction.date) == now.year, 
            extract('month', models.Transaction.date) == now.month
        ).scalar() or 0.0

        rem = b.monthly_limit - spent
        pct = round((spent / b.monthly_limit) * 100, 1) if b.monthly_limit > 0 else 0.0

        result.append(schemas.BudgetProgressResponse(
            id=b.id,
            category=b.category,
            monthly_limit=round(b.monthly_limit, 2),
            spent=round(spent, 2),
            remaining=round(rem, 2),
            percentage=pct,
            status="exceeded" if spent > b.monthly_limit else ("warning" if pct >= 85 else "on_track")
        ))

    return result


@router.get("/summary", response_model=schemas.BudgetSummaryResponse)
def get_budgets_summary(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Tüm bütçelerin toplam limit ve toplam harcama özetini döner."""
    budgets = db.query(models.Budget).filter(models.Budget.user_id == current_user.id).all()
    total_budget = sum(b.monthly_limit for b in budgets) if budgets else 0.0

    now = datetime.datetime.now()
    if budgets:
        budget_categories = [b.category for b in budgets]
        total_spent = db.query(func.sum(models.Transaction.amount)).filter(
            models.Transaction.type == "expense",
            models.Transaction.user_id == current_user.id,
            models.Transaction.category.in_(budget_categories),
            extract('year', models.Transaction.date) == now.year, 
            extract('month', models.Transaction.date) == now.month
        ).scalar() or 0.0
    else:
        total_spent = 0.0

    rem = total_budget - total_spent
    pct = round((total_spent / total_budget) * 100, 1) if total_budget > 0 else 0.0

    return schemas.BudgetSummaryResponse(
        total_budget=round(total_budget, 2),
        total_spent=round(total_spent, 2),
        remaining=round(rem, 2),
        percentage=pct
    )


@router.delete("/{budget_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_budget(
    budget_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Mevcut bir bütçe kuralını siler."""
    budget = db.query(models.Budget).filter(
        models.Budget.id == budget_id,
        models.Budget.user_id == current_user.id
    ).first()
    if not budget:
        raise HTTPException(status_code=404, detail="Bütçe bulunamadı veya silme yetkiniz yok.")

    db.delete(budget)
    db.commit()
    return None
