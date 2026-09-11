from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import extract
from typing import List, Optional
import datetime

from database import get_db
import models
import schemas
from auth import get_current_user
from services.recurring_service import process_recurring_transactions

router = APIRouter(prefix="/api", tags=["İşlemler"])


@router.post("/transactions")
def create_transaction(
    transaction: schemas.TransactionCreate, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    base_date = transaction.date if transaction.date else datetime.datetime.utcnow()
    repeat = transaction.repeat_months if (transaction.repeat_months and transaction.repeat_months > 1) else 1
    
    # 1. Yalnızca İLK AYIN işlemini kaydediyoruz (böylece sadece bu ayın parası düşer!)
    desc = transaction.description or transaction.category
    if repeat > 1:
        desc = f"{desc} (1/{repeat})"
        
    db_tx = models.Transaction(
        user_id=current_user.id,
        type=transaction.type,
        amount=transaction.amount,
        category=transaction.category,
        description=desc,
        date=base_date,
        currency=transaction.currency or "TRY",
        original_amount=transaction.original_amount if transaction.original_amount is not None else transaction.amount,
        exchange_rate=transaction.exchange_rate or 1.0
    )
    db.add(db_tx)
    
    # 2. Eğer birden fazla ay sürecekse, kuralı recurring_transactions tablosuna kaydediyoruz:
    if repeat > 1:
        recurring_rule = models.RecurringTransaction(
            user_id=current_user.id,
            type=transaction.type,
            amount=transaction.amount,
            category=transaction.category,
            description=transaction.description or transaction.category,
            day_of_month=base_date.day,
            total_months=repeat,
            paid_months=1,
            last_payment_date=base_date,
            is_active=1
        )
        db.add(recurring_rule)
        
    db.commit()
    db.refresh(db_tx)
    return db_tx


@router.post("/transactions/batch")
def batch_create_transactions(
    items: List[schemas.TransactionCreate],
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Banka ekstresi veya toplu aktarımlar için birden fazla işlemi tek seferde kaydeder."""
    if not items:
        raise HTTPException(status_code=400, detail="Kaydedilecek işlem bulunamadı.")
    
    created_records = []
    for item in items:
        base_date = item.date if item.date else datetime.datetime.utcnow()
        db_tx = models.Transaction(
            user_id=current_user.id,
            type=item.type,
            amount=item.amount,
            category=item.category,
            description=item.description or item.category,
            date=base_date,
            currency=item.currency or "TRY",
            original_amount=item.original_amount if item.original_amount is not None else item.amount,
            exchange_rate=item.exchange_rate or 1.0
        )
        db.add(db_tx)
        created_records.append(db_tx)
    
    db.commit()
    return {
        "success": True,
        "count": len(created_records),
        "message": f"{len(created_records)} adet işlem başarıyla harcamalarınıza eklendi!"
    }


@router.get("/transactions", response_model=List[schemas.TransactionResponse])
def list_transactions(
    type: Optional[str] = Query(None, description="'income' veya 'expense' filtresi"),
    category: Optional[str] = Query(None, description="Kategori filtresi"),
    month: Optional[str] = Query(None, description="YYYY-MM formatında ay filtresi"),
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Önce günü gelen tekrarlayan ödemeleri işle:
    process_recurring_transactions(db, current_user.id)
    
    # Sadece giriş yapmış olan kullanıcının işlemlerini getir:
    query = db.query(models.Transaction).filter(models.Transaction.user_id == current_user.id)
    
    if type:
        query = query.filter(models.Transaction.type == type)
        
    if category:
        query = query.filter(models.Transaction.category == category)
        
    if month and month != "all":
        try:
            year_str, month_str = month.split("-")
            query = query.filter(
                extract('year', models.Transaction.date) == int(year_str),
                extract('month', models.Transaction.date) == int(month_str)
            )
        except ValueError:
            pass
    
    return query.order_by(models.Transaction.date.desc()).limit(limit).all()


@router.delete("/transactions/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(
    transaction_id: int, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Kullanıcı sadece kendi işlemini silebilir:
    db_tx = db.query(models.Transaction).filter(
        models.Transaction.id == transaction_id,
        models.Transaction.user_id == current_user.id
    ).first()
    
    if not db_tx:
        raise HTTPException(status_code=404, detail="İşlem bulunamadı veya bu işlemi silme yetkiniz yok.")
    db.delete(db_tx)
    db.commit()
    return None


@router.get("/categories", response_model=List[schemas.CategoryResponse], tags=["Kategoriler"])
def list_categories(
    type: Optional[str] = Query(None, description="'income' veya 'expense' filtresi"),
    db: Session = Depends(get_db)
):
    """Veritabanındaki dinamik kategorileri listeler."""
    query = db.query(models.Category)
    if type:
        query = query.filter(models.Category.type == type)
    return query.all()


@router.get("/recurring-transactions", response_model=List[schemas.RecurringTransactionResponse])
def get_recurring_transactions(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    process_recurring_transactions(db, current_user.id)
    return db.query(models.RecurringTransaction).filter(
        models.RecurringTransaction.user_id == current_user.id
    ).order_by(models.RecurringTransaction.created_at.desc()).all()


@router.post("/recurring-transactions", response_model=schemas.RecurringTransactionResponse)
def create_recurring_transaction(
    item: schemas.RecurringTransactionCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Yeni bir düzenli gelir veya gider kuralı oluşturur."""
    rec = models.RecurringTransaction(
        user_id=current_user.id,
        type=item.type,
        amount=item.amount,
        category=item.category,
        description=item.description or item.category,
        day_of_month=item.day_of_month,
        total_months=item.total_months,
        paid_months=0,
        last_payment_date=None,
        is_active=1
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)

    # Seçilen gün bugün veya geçmişteyse hemen bu ayın işlemini ekle
    process_recurring_transactions(db, current_user.id)
    db.refresh(rec)
    return rec


@router.post("/recurring-transactions/{recurring_id}/run-now")
def run_recurring_transaction_now(
    recurring_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if not getattr(current_user, "is_admin", False):
        raise HTTPException(status_code=403, detail="Bu test işlemi yalnızca yöneticilere (admin) özeldir.")

    rec = db.query(models.RecurringTransaction).filter(
        models.RecurringTransaction.id == recurring_id,
        models.RecurringTransaction.user_id == current_user.id
    ).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Düzenli işlem bulunamadı")

    now = datetime.datetime.utcnow()
    rec.paid_months += 1
    rec.last_payment_date = now

    desc = f"{rec.description or rec.category}"
    if rec.total_months < 100 and rec.total_months > 0:
        desc += f" ({rec.paid_months}/{rec.total_months})"

    new_tx = models.Transaction(
        user_id=current_user.id,
        type=rec.type,
        amount=rec.amount,
        category=rec.category,
        description=desc,
        date=now
    )
    db.add(new_tx)

    if rec.paid_months >= rec.total_months:
        rec.is_active = 0

    db.commit()
    return {"message": f"'{rec.description or rec.category}' işlemi başarıyla tetiklendi ve İşlemler tablosuna eklendi! ⚡"}


@router.put("/recurring-transactions/{recurring_id}", response_model=schemas.RecurringTransactionResponse)
def update_recurring_transaction(
    recurring_id: int,
    item: schemas.RecurringTransactionUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Mevcut bir düzenli işlem kuralını günceller."""
    rec = db.query(models.RecurringTransaction).filter(
        models.RecurringTransaction.id == recurring_id,
        models.RecurringTransaction.user_id == current_user.id
    ).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Düzenli işlem kaydı bulunamadı!")

    if item.type is not None:
        rec.type = item.type
    if item.amount is not None:
        rec.amount = item.amount
    if item.category is not None:
        rec.category = item.category
    if item.description is not None:
        rec.description = item.description
    if item.day_of_month is not None:
        rec.day_of_month = item.day_of_month
    if item.total_months is not None:
        rec.total_months = item.total_months
    if item.is_active is not None:
        rec.is_active = item.is_active

    db.commit()
    db.refresh(rec)
    return rec


@router.delete("/recurring-transactions/{recurring_id}")
def delete_recurring_transaction(
    recurring_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Mevcut bir düzenli işlem kuralını siler."""
    rec = db.query(models.RecurringTransaction).filter(
        models.RecurringTransaction.id == recurring_id,
        models.RecurringTransaction.user_id == current_user.id
    ).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Düzenli işlem kaydı bulunamadı!")

    db.delete(rec)
    db.commit()
    return {"message": "Düzenli işlem kuralı başarıyla silindi."}


@router.post("/recurring-transactions/{recurring_id}/toggle")
def toggle_recurring_transaction(
    recurring_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Düzenli işlemin aktif/duraklatıldı durumunu değiştirir."""
    rec = db.query(models.RecurringTransaction).filter(
        models.RecurringTransaction.id == recurring_id,
        models.RecurringTransaction.user_id == current_user.id
    ).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Düzenli işlem kaydı bulunamadı!")

    rec.is_active = 0 if rec.is_active == 1 else 1
    db.commit()
    status_str = "aktif edildi" if rec.is_active == 1 else "duraklatıldı"
    return {"message": f"Düzenli işlem başarıyla {status_str}.", "is_active": rec.is_active}
