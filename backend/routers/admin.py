from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from typing import List
import datetime
import time

from database import get_db
import models
import schemas
from auth import get_current_admin_user
import ai_service

router = APIRouter(prefix="/api/admin", tags=["Yönetici Paneli"])


@router.get("/stats", response_model=schemas.AdminStatsResponse)
def get_admin_stats(
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_current_admin_user)
):
    """Sistem genelindeki KPI metriklerini döner."""
    total_users = db.query(models.User).count()
    total_tx = db.query(models.Transaction).count()
    vol_sum = db.query(func.sum(models.Transaction.amount)).scalar() or 0.0
    total_goals = db.query(models.Goal).count()
    
    # AI Token & İstek İstatistikleri
    token_stats = db.query(
        func.coalesce(func.sum(models.AITokenUsage.total_tokens), 0),
        func.coalesce(func.sum(models.AITokenUsage.prompt_tokens), 0),
        func.coalesce(func.sum(models.AITokenUsage.completion_tokens), 0),
        func.count(models.AITokenUsage.id)
    ).first()

    total_ai_tokens = int(token_stats[0]) if token_stats else 0
    prompt_tokens = int(token_stats[1]) if token_stats else 0
    completion_tokens = int(token_stats[2]) if token_stats else 0
    total_ai_requests = int(token_stats[3]) if token_stats else 0
    
    seven_days_ago = datetime.datetime.utcnow() - datetime.timedelta(days=7)
    new_users = db.query(models.User).filter(models.User.created_at >= seven_days_ago).count()
    
    return schemas.AdminStatsResponse(
        total_users=total_users,
        total_transactions=total_tx,
        total_volume=round(float(vol_sum), 2),
        total_goals=total_goals,
        total_chat_messages=0,
        total_ai_tokens=total_ai_tokens,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_ai_requests=total_ai_requests,
        new_users_last_7_days=new_users
    )


@router.get("/users", response_model=List[schemas.AdminUserItem])
def get_admin_users(
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_current_admin_user)
):
    """Tüm kullanıcıları, işlem sayılarını ve harcama toplamlarını döner."""
    users = db.query(models.User).order_by(models.User.id.desc()).all()
    user_list = []
    
    for u in users:
        tx_count = db.query(models.Transaction).filter(models.Transaction.user_id == u.id).count()
        spent = db.query(func.sum(models.Transaction.amount)).filter(
            models.Transaction.user_id == u.id,
            models.Transaction.type == "expense"
        ).scalar() or 0.0
        income = db.query(func.sum(models.Transaction.amount)).filter(
            models.Transaction.user_id == u.id,
            models.Transaction.type == "income"
        ).scalar() or 0.0
        
        user_list.append(schemas.AdminUserItem(
            id=u.id,
            full_name=u.full_name,
            email=u.email,
            is_admin=bool(getattr(u, "is_admin", False)),
            is_active=bool(getattr(u, "is_active", True)),
            created_at=u.created_at or datetime.datetime.utcnow(),
            transactions_count=tx_count,
            total_spent=round(float(spent), 2),
            total_income=round(float(income), 2)
        ))
        
    return user_list


@router.post("/users/{user_id}/toggle-admin")
def toggle_user_admin(
    user_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_current_admin_user)
):
    """Kullanıcının admin yetkisini açar veya kapatır."""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Kendi admin yetkinizi kaldıramazsınız!")
        
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı!")
        
    user.is_admin = not getattr(user, "is_admin", False)
    db.commit()
    return {"message": f"{user.full_name} kullanıcısının admin yetkisi {'verildi' if user.is_admin else 'alındı'}.", "is_admin": user.is_admin}


@router.post("/users/{user_id}/role")
def update_user_role(
    user_id: int,
    payload: schemas.UserRoleUpdate,
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_current_admin_user)
):
    """Kullanıcının rolünü doğrudan 'admin' veya 'user' olarak ayarlar."""
    target_role = payload.role.strip().lower()
    if target_role not in ["admin", "user"]:
        raise HTTPException(status_code=400, detail="Geçersiz rol! Lütfen 'admin' veya 'user' seçin.")

    if user_id == admin.id and target_role != "admin":
        raise HTTPException(status_code=400, detail="Kendi admin yetkinizi kaldıramazsınız!")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı!")

    user.is_admin = (target_role == "admin")
    if hasattr(user, "role"):
        user.role = target_role
    db.commit()

    role_text = "Yönetici (Admin)" if user.is_admin else "Standart Kullanıcı"
    return {
        "message": f"{user.full_name} kullanıcısının rolü '{role_text}' olarak güncellendi.",
        "is_admin": user.is_admin,
        "role": target_role
    }


@router.post("/users/{user_id}/toggle-active")
def toggle_user_active(
    user_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_current_admin_user)
):
    """Kullanıcının hesabını askıya alır veya yeniden aktif eder."""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Kendi hesabınızı askıya alamazsınız!")
        
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı!")
        
    user.is_active = not getattr(user, "is_active", True)
    db.commit()
    return {"message": f"{user.full_name} hesabı {'aktif edildi' if user.is_active else 'askıya alındı'}.", "is_active": user.is_active}


@router.delete("/users/{user_id}")
def delete_user_by_admin(
    user_id: int,
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_current_admin_user)
):
    """Kullanıcıyı ve ilişkili tüm verilerini sistemden siler."""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Kendi hesabınızı silemezsiniz!")
        
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı!")
        
    # Kullanıcının ilişkili kayıtlarını temizle
    db.query(models.Transaction).filter(models.Transaction.user_id == user_id).delete()
    db.query(models.RecurringTransaction).filter(models.RecurringTransaction.user_id == user_id).delete()
    db.query(models.Budget).filter(models.Budget.user_id == user_id).delete()
    db.query(models.Goal).filter(models.Goal.user_id == user_id).delete()
    db.delete(user)
    db.commit()
    return {"message": f"{user.full_name} kullanıcısı ve tüm verileri silindi."}


@router.get("/system-health")
def get_system_health(
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_current_admin_user)
):
    """Sistem bileşenlerinin canlılık ve sağlık durumunu denetler."""
    start_time = time.time()
    gemini_ready = bool(getattr(ai_service, "GEMINI_API_KEY", ""))
    
    health_data = {
        "status": "healthy",
        "database": False,
        "gemini_api": gemini_ready,
        "latency_ms": 0,
        "message": "Tüm sistemler çalışır durumda."
    }

    # 1. Veritabanı canlılık testi (SELECT 1 sorgusu)
    try:
        db.execute(text("SELECT 1"))
        health_data["database"] = True
    except Exception as e:
        health_data["status"] = "error"
        health_data["database"] = False
        health_data["message"] = f"Veritabanı hatası: {str(e)}"

    # 2. Gecikme (Latency) hesaplama
    latency = round((time.time() - start_time) * 1000, 2)
    health_data["latency_ms"] = latency

    return health_data
