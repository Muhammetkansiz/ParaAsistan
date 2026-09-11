# backend/routers/goals.py
# ParaAsistan - Birikim Hedefleri Router Modülü

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
import datetime
from database import get_db
import models
import schemas
from auth import get_current_user

router = APIRouter(prefix="/api/goals", tags=["Hedefler"])

def format_goal_response(goal: models.Goal) -> schemas.GoalResponse:
    """Veritabanındaki hedef kaydını hesaplanmış yüzdeler ve kalan gün ile döner."""
    pct = round((goal.current_amount / goal.target_amount) * 100, 1) if goal.target_amount > 0 else 0.0
    rem_amount = max(0.0, round(goal.target_amount - goal.current_amount, 2))
    
    rem_days = None
    if goal.target_date:
        diff = (goal.target_date.date() - datetime.date.today()).days
        rem_days = max(0, diff)
        
    return schemas.GoalResponse(
        id=goal.id,
        user_id=goal.user_id,
        title=goal.title,
        target_amount=round(goal.target_amount, 2),
        current_amount=round(goal.current_amount, 2),
        remaining_amount=rem_amount,
        percentage=pct,
        target_date=goal.target_date,
        remaining_days=rem_days,
        category=goal.category,
        icon=goal.icon,
        color=goal.color,
        status="completed" if goal.current_amount >= goal.target_amount else goal.status,
        created_at=goal.created_at
    )


@router.get("", response_model=schemas.GoalsSummaryResponse)
def list_user_goals(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Kullanıcının tüm hedeflerini ve genel birikim ilerleme özetini döner."""
    goals = db.query(models.Goal).filter(models.Goal.user_id == current_user.id).order_by(models.Goal.created_at.desc()).all()
    
    total_saved = sum(g.current_amount for g in goals)
    total_target = sum(g.target_amount for g in goals)
    overall_pct = round((total_saved / total_target) * 100, 1) if total_target > 0 else 0.0
    
    formatted_goals = [format_goal_response(g) for g in goals]
    completed_count = sum(1 for g in formatted_goals if g.status == "completed")
    active_count = len(formatted_goals) - completed_count
    
    return schemas.GoalsSummaryResponse(
        total_saved=round(total_saved, 2),
        total_target=round(total_target, 2),
        overall_percentage=overall_pct,
        active_goals_count=active_count,
        completed_goals_count=completed_count,
        goals=formatted_goals
    )


@router.post("", response_model=schemas.GoalResponse)
def create_user_goal(
    goal_data: schemas.GoalCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Yeni bir birikim hedefi oluşturur."""
    new_goal = models.Goal(
        user_id=current_user.id,
        title=goal_data.title,
        target_amount=goal_data.target_amount,
        current_amount=goal_data.current_amount or 0.0,
        target_date=goal_data.target_date,
        category=goal_data.category or "Genel",
        icon=goal_data.icon or "flag",
        color=goal_data.color or "#1a237e",
        status="completed" if (goal_data.current_amount or 0.0) >= goal_data.target_amount else "in_progress"
    )
    db.add(new_goal)
    db.commit()
    db.refresh(new_goal)
    return format_goal_response(new_goal)


@router.post("/{goal_id}/deposit", response_model=schemas.GoalResponse)
def deposit_to_goal(
    goal_id: int,
    deposit: schemas.GoalDeposit,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Mevcut bir hedefe birikim / para ekler."""
    goal = db.query(models.Goal).filter(
        models.Goal.id == goal_id,
        models.Goal.user_id == current_user.id
    ).first()
    
    if not goal:
        raise HTTPException(status_code=404, detail="Hedef bulunamadı!")
        
    goal.current_amount += deposit.amount
    if goal.current_amount >= goal.target_amount:
        goal.status = "completed"
        
    db.commit()
    db.refresh(goal)
    return format_goal_response(goal)


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goal(
    goal_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Belirtilen hedefi siler."""
    goal = db.query(models.Goal).filter(
        models.Goal.id == goal_id,
        models.Goal.user_id == current_user.id
    ).first()
    
    if not goal:
        raise HTTPException(status_code=404, detail="Hedef bulunamadı!")
        
    db.delete(goal)
    db.commit()
    return None
