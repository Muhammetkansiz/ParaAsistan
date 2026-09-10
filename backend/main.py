from fastapi import FastAPI, Depends, HTTPException, Query, status, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, text
from typing import List, Optional
import datetime
import calendar
import time
from database import engine, Base, get_db, SessionLocal
import models
import schemas
from auth import get_current_user
import currency_service
import statement_service

# 🚀 Tabloları veritabanında otomatik oluştur (yoksa)
Base.metadata.create_all(bind=engine)

# 🔄 Otomatik Veritabanı Kolon Eşitleme (Migration)
def migrate_db_columns():
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS currency VARCHAR DEFAULT 'TRY';"))
            conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS original_amount FLOAT;"))
            conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS exchange_rate FLOAT DEFAULT 1.0;"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE;"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;"))
            # Eski atıl chat_messages tablosunu temizle
            try:
                conn.execute(text("DROP TABLE IF EXISTS chat_messages CASCADE;"))
            except Exception:
                pass
            # İlk kayıtlı kullanıcıyı otomatik admin yapalım
            conn.execute(text("UPDATE users SET is_admin = TRUE WHERE id = (SELECT min(id) FROM users);"))
        print("✅ Veritabanı kolonları ve admin yetkisi başarıyla eşitlendi.")
    except Exception as e:
        print("⚠️ Migration uyarısı:", e)

migrate_db_columns()

def seed_default_categories():
    """Yeni açılan veritabanına varsayılan kategorileri otomatik ekler."""
    db = SessionLocal()
    try:
        if db.query(models.Category).count() == 0:
            default_cats = [
                models.Category(name="Market", type="expense", icon="shopping_cart", color="#e11d48"),
                models.Category(name="Kira", type="expense", icon="home", color="#2563eb"),
                models.Category(name="Fatura", type="expense", icon="bolt", color="#d97706"),
                models.Category(name="Ulaşım", type="expense", icon="directions_car", color="#059669"),
                models.Category(name="Teknoloji", type="expense", icon="laptop", color="#7c3aed"),
                models.Category(name="Eğlence", type="expense", icon="movie", color="#db2777"),
                models.Category(name="Sağlık", type="expense", icon="medical_services", color="#dc2626"),
                models.Category(name="Eğitim", type="expense", icon="school", color="#4f46e5"),
                models.Category(name="Diğer", type="expense", icon="receipt", color="#64748b"),
                models.Category(name="Maaş", type="income", icon="payments", color="#16a34a"),
                models.Category(name="Ek Gelir", type="income", icon="savings", color="#0d9488"),
                models.Category(name="Yatırım", type="income", icon="trending_up", color="#0284c7"),
                models.Category(name="Diğer Gelir", type="income", icon="receipt", color="#64748b"),
            ]
            db.add_all(default_cats)
            db.commit()
            print("✅ Varsayılan kategoriler başarıyla veritabanına yüklendi.")
    except Exception as e:
        db.rollback()
        print("⚠️ Kategoriler başlatılırken uyarı:", e)
    finally:
        db.close()

seed_default_categories()

app = FastAPI(
    title="ParaAsistan API",
    description="Akıllı Finans ve Bütçe Yönetimi API'si",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_origin_regex=".*",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", tags=["Sistem"])
def health_check():
    return {"status": "ok", "message": "ParaAsistan API sorunsuz çalışıyor"}


@app.get("/api/currency/rates", tags=["Döviz & Kurlar"])
def get_exchange_rates():
    """Frankfurter (Avrupa Merkez Bankası) üzerinden güncel canlı döviz kurlarını döner."""
    return currency_service.get_live_rates()


def process_recurring_transactions(db: Session, user_id: int):
    """
    Günü gelmiş olan tekrarlayan ödemeleri kontrol eder ve gerekirse
    transactions tablosuna yeni ayın işlemini ekler.
    """
    now = datetime.datetime.utcnow()
    active_rules = db.query(models.RecurringTransaction).filter(
        models.RecurringTransaction.user_id == user_id,
        models.RecurringTransaction.is_active == 1,
        models.RecurringTransaction.paid_months < models.RecurringTransaction.total_months
    ).all()

    for rule in active_rules:
        while rule.paid_months < rule.total_months:
            if rule.last_payment_date is None:
                # İlk ödeme: Kuralın oluşturulduğu ayın seçilen günü
                start_year = rule.created_at.year
                start_month = rule.created_at.month
                max_days = calendar.monthrange(start_year, start_month)[1]
                target_day = min(rule.day_of_month, max_days)
                candidate_date = datetime.datetime(
                    start_year, start_month, target_day,
                    rule.created_at.hour, rule.created_at.minute, rule.created_at.second
                )
            else:
                # Bir sonraki ayın seçilen günü
                last = rule.last_payment_date
                total_m = last.year * 12 + (last.month - 1) + 1
                next_year = total_m // 12
                next_month = (total_m % 12) + 1
                max_days = calendar.monthrange(next_year, next_month)[1]
                target_day = min(rule.day_of_month, max_days)
                candidate_date = datetime.datetime(
                    next_year, next_month, target_day,
                    last.hour, last.minute, last.second
                )

            # Tarih karşılaştırması: Belirlenen gün bugün veya geçmişteyse işlemi oluştur
            if now.date() >= candidate_date.date():
                rule.paid_months += 1
                rule.last_payment_date = candidate_date
                
                desc = f"{rule.description or rule.category}"
                if rule.total_months < 100 and rule.total_months > 0:
                    desc += f" ({rule.paid_months}/{rule.total_months})"
                
                new_tx = models.Transaction(
                    user_id=user_id,
                    type=rule.type,
                    amount=rule.amount,
                    category=rule.category,
                    description=desc,
                    date=candidate_date
                )
                db.add(new_tx)
                
                if rule.paid_months >= rule.total_months:
                    rule.is_active = 0
                    break
            else:
                # Henüz günü gelmedi
                break
                
    db.commit()


@app.post("/api/transactions", tags=["İşlemler"])
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

@app.post("/api/transactions/batch", tags=["İşlemler"])
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

@app.get("/api/transactions", response_model=List[schemas.TransactionResponse], tags=["İşlemler"])
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



@app.delete("/api/transactions/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["İşlemler"])
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

@app.get("/api/categories", response_model=List[schemas.CategoryResponse], tags=["Kategoriler"])
def list_categories(
    type: Optional[str] = Query(None, description="'income' veya 'expense' filtresi"),
    db: Session = Depends(get_db)
):
    """Veritabanındaki dinamik kategorileri listeler."""
    query = db.query(models.Category)
    if type:
        query = query.filter(models.Category.type == type)
    return query.all()



@app.get("/api/recurring-transactions", response_model=List[schemas.RecurringTransactionResponse], tags=["İşlemler"])
def get_recurring_transactions(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    process_recurring_transactions(db, current_user.id)
    return db.query(models.RecurringTransaction).filter(
        models.RecurringTransaction.user_id == current_user.id
    ).order_by(models.RecurringTransaction.created_at.desc()).all()


@app.post("/api/recurring-transactions", response_model=schemas.RecurringTransactionResponse, tags=["İşlemler"])
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


@app.post("/api/recurring-transactions/{recurring_id}/run-now", tags=["İşlemler"])
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


@app.put("/api/recurring-transactions/{recurring_id}", response_model=schemas.RecurringTransactionResponse, tags=["İşlemler"])
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


@app.delete("/api/recurring-transactions/{recurring_id}", tags=["İşlemler"])
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


@app.post("/api/recurring-transactions/{recurring_id}/toggle", tags=["İşlemler"])
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


@app.get("/api/analytics/summary", response_model=schemas.SummaryResponse, tags=["Analiz"])
def get_financial_summary(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    process_recurring_transactions(db, current_user.id)
    income = db.query(func.sum(models.Transaction.amount)).filter(
        models.Transaction.type == "income",
        models.Transaction.user_id == current_user.id
    ).scalar() or 0.0

    expense = db.query(func.sum(models.Transaction.amount)).filter(
        models.Transaction.type == "expense",
        models.Transaction.user_id == current_user.id
    ).scalar() or 0.0

    net = income - expense
    savings_rate = ((income - expense) / income * 100) if income > 0 else 0.0
    return schemas.SummaryResponse(
        total_income=round(income, 2),
        total_expense=round(expense, 2),
        net_balance=round(net, 2),
        savings_rate=round(max(savings_rate, 0.0), 1)
    )

@app.get("/api/analytics/monthly-cashflow", tags=["Analiz"])
def get_monthly_cashflow(
    period: str = "6months",
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Türkçe ay isimleri
    turkish_months = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", 
                      "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
    
    now = datetime.datetime.now()
    months_data = []

    # 1. "Bu Ay" seçildiyse son 4 haftalık (28 gün) hareketli kırılım göster
    if period == "month":
        for w in range(3, -1, -1):
            end_date = now - datetime.timedelta(days=w*7)
            start_date = end_date - datetime.timedelta(days=6)
            s_dt = datetime.datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0)
            e_dt = datetime.datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59)
            s_abbr = turkish_months[start_date.month - 1][:3]
            e_abbr = turkish_months[end_date.month - 1][:3]
            label = f"{start_date.day}-{end_date.day} {s_abbr}" if start_date.month == end_date.month else f"{start_date.day} {s_abbr}-{end_date.day} {e_abbr}"

            inc = db.query(func.sum(models.Transaction.amount)).filter(
                models.Transaction.type == "income",
                models.Transaction.user_id == current_user.id,
                models.Transaction.date >= s_dt,
                models.Transaction.date <= e_dt
            ).scalar() or 0.0

            exp = db.query(func.sum(models.Transaction.amount)).filter(
                models.Transaction.type == "expense",
                models.Transaction.user_id == current_user.id,
                models.Transaction.date >= s_dt,
                models.Transaction.date <= e_dt
            ).scalar() or 0.0

            months_data.append({
                "month": label,
                "year": end_date.year,
                "income": round(inc, 2),
                "expense": round(exp, 2)
            })
        return months_data
    
    # 2. İstenen periyoda göre geriye kaç ay hesaplanacağını belirle:
    if period == "3months":
        count = 3
    elif period == "year":
        # Mevcut yılın başından (Ocak) bu aya kadar:
        count = now.month
    elif period == "all":
        # Son 12 ay:
        count = 12
    else:
        # Varsayılan: Son 6 ay
        count = 6
    
    for i in range(count - 1, -1, -1):
        # Toplam ay hesabı üzerinden yıl ve ay indeksini bul (yıl geçişlerini kusursuz çözer)
        total_months = now.year * 12 + (now.month - 1) - i
        year = total_months // 12
        month_idx = total_months % 12
        month_num = month_idx + 1
        month_name = turkish_months[month_idx]
        
        # Bu ayki kullanıcının gelirlerini topla
        inc = db.query(func.sum(models.Transaction.amount)).filter(
            models.Transaction.type == "income",
            models.Transaction.user_id == current_user.id,
            extract('year', models.Transaction.date) == year,
            extract('month', models.Transaction.date) == month_num
        ).scalar() or 0.0
        
        # Bu ayki kullanıcının giderlerini topla
        exp = db.query(func.sum(models.Transaction.amount)).filter(
            models.Transaction.type == "expense",
            models.Transaction.user_id == current_user.id,
            extract('year', models.Transaction.date) == year,
            extract('month', models.Transaction.date) == month_num
        ).scalar() or 0.0
        
        label = f"{month_name[:3]} '{str(year)[2:]}" if count > 6 else month_name

        months_data.append({
            "month": label,
            "year": year,
            "income": round(inc, 2),
            "expense": round(exp, 2)
        })
        
    return months_data


@app.get("/api/analytics/category-spending", tags=["Analiz"])
def get_category_spending(
    period: str = "month",
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    now = datetime.datetime.now()
    
    if period == "month":
        start_date = datetime.datetime(now.year, now.month, 1)
    elif period == "3months":
        total_m = now.year * 12 + (now.month - 1) - 2
        start_date = datetime.datetime(total_m // 12, (total_m % 12) + 1, 1)
    elif period == "6months":
        total_m = now.year * 12 + (now.month - 1) - 5
        start_date = datetime.datetime(total_m // 12, (total_m % 12) + 1, 1)
    elif period == "year":
        start_date = datetime.datetime(now.year, 1, 1)
    elif period == "all":
        total_m = now.year * 12 + (now.month - 1) - 11
        start_date = datetime.datetime(total_m // 12, (total_m % 12) + 1, 1)
    else:
        start_date = datetime.datetime(now.year, now.month, 1)

    results = db.query(
        models.Transaction.category,
        func.sum(models.Transaction.amount).label("total")
    ).filter(
        models.Transaction.type == "expense",
        models.Transaction.user_id == current_user.id,
        models.Transaction.date >= start_date
    ).group_by(models.Transaction.category).all()
    
    total_spent = sum(r.total for r in results) if results else 0.0
    
    data = []
    for r in results:
        pct = round((r.total / total_spent) * 100, 1) if total_spent > 0 else 0.0
        data.append({
            "category": r.category,
            "amount": round(r.total, 2),
            "percentage": pct
        })
        
    # En çok harcanandan en aza doğru sırala
    data.sort(key=lambda x: x["amount"], reverse=True)
        
    return {
        "period": period,
        "total_spent": round(total_spent, 2),
        "categories": data
    }


@app.post("/api/budgets", response_model=schemas.BudgetProgressResponse, tags=["Bütçeler"])
def create_or_update_budget(
    budget: schemas.BudgetCreate, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Sadece bu kullanıcının o kategorideki bütçesini bul:
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

    # Bu ayki harcamayı hesapla (Kullanıcıya özel)
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

@app.get("/api/budgets", response_model=List[schemas.BudgetProgressResponse], tags=["Bütçeler"])
def get_budgets_progress(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Sadece bu kullanıcının bütçelerini getir:
    budgets = db.query(models.Budget).filter(models.Budget.user_id == current_user.id).all()
    
    if not budgets:
        return []

    now = datetime.datetime.now()
    result = []
    for b in budgets:
        # Harcamalar sadece bu kullanıcıya ait olsun:
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

@app.get("/api/budgets/summary", response_model=schemas.BudgetSummaryResponse, tags=["Bütçeler"])
def get_budgets_summary(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Sadece bu kullanıcının bütçelerini topla:
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


@app.delete("/api/budgets/{budget_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Bütçeler"])
def delete_budget(
    budget_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    budget = db.query(models.Budget).filter(
        models.Budget.id == budget_id,
        models.Budget.user_id == current_user.id
    ).first()
    if not budget:
        raise HTTPException(status_code=404, detail="Bütçe bulunamadı veya silme yetkiniz yok.")

    db.delete(budget)
    db.commit()
    return None


import ai_service
from pydantic import BaseModel

class ChatRequest(BaseModel):
    message: str

@app.post("/api/ai/chat", tags=["Yapay Zeka"])
async def chat_with_ai(
    req: ChatRequest, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    result = await ai_service.ask_financial_advisor(req.message, db, user_id=current_user.id)
    return result


@app.get("/api/ai/panel-context", tags=["Yapay Zeka"])
def get_ai_panel_context(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    return ai_service.get_panel_context(db, user_id=current_user.id)


@app.get("/api/ai/daily-briefing", tags=["Yapay Zeka"])
async def get_daily_briefing(
    force_refresh: bool = Query(False, description="Zorla yenileme bayrağı"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Kullanıcının gerçek finansal verilerini analiz edip kişiselleştirilmiş günlük AI brifingi döner."""
    briefing = await ai_service.generate_daily_briefing(db, current_user.id, force_refresh=force_refresh)
    return briefing


@app.post("/api/ai/scan-receipt", tags=["Yapay Zeka"])
async def scan_receipt(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Kullanıcının yüklediği fiş, fatura veya banka ekstresini (Görsel, PDF, CSV) analiz eder."""
    allowed_types = ["image/", "application/pdf", "text/csv", "application/csv", "text/plain", "application/vnd.ms-excel"]
    fname = (file.filename or "").lower()
    is_valid_type = any(file.content_type and file.content_type.startswith(t) for t in allowed_types) or fname.endswith((".csv", ".pdf", ".png", ".jpg", ".jpeg", ".webp"))

    if not is_valid_type:
        raise HTTPException(
            status_code=400, 
            detail="Lütfen geçerli bir fiş/dekont görseli (JPEG/PNG), banka ekstresi (PDF) veya CSV dökümü yükleyin."
        )

    contents = await file.read()
    doc_data = await statement_service.parse_statement_with_gemini(contents, file.content_type or "application/octet-stream", filename=file.filename or "")
    
    # Token kullanımını kaydet
    if "usage_metadata" in doc_data and doc_data["usage_metadata"]:
        feature_name = "statement_scan" if doc_data.get("is_statement") else "receipt_scan"
        model_name = doc_data.get("model_used", "gemini-3.6-flash")
        ai_service.log_token_usage(db, current_user.id, model_name, feature_name, doc_data.get("usage_metadata"))

    # Guardrails: Eğer finansal evrak harici uygunsuz bir belge tespit edildiyse reddet
    is_valid = doc_data.get("is_valid_document", True)
    if not doc_data.get("is_statement"):
        is_valid = is_valid and doc_data.get("is_valid_receipt", True)
    if not is_valid:
        raise HTTPException(
            status_code=400, 
            detail=doc_data.get("error", "Yüklenen belge geçerli bir fiş veya banka ekstresi değildir. Güvenlik politikası gereği kimlik veya kart belgeleri işlenemez.")
        )

    return doc_data



# --- KİMLİK DOĞRULAMA (AUTH) KAPILARI ---
import auth

@app.post("/api/auth/register", response_model=schemas.UserResponse, tags=["Kimlik Doğrulama"])
def register(user_data: schemas.UserCreate, db: Session = Depends(get_db)):
    existing_user = db.query(models.User).filter(models.User.email == user_data.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Bu e-posta adresi zaten kayıtlı!")

    hashed_pwd = auth.hash_password(user_data.password)

    new_user = models.User(
        full_name=user_data.full_name,
        email=user_data.email,
        hashed_password=hashed_pwd
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@app.post("/api/auth/login", tags=["Kimlik Doğrulama"])
def login(login_data: schemas.UserLogin, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == login_data.email).first()
    if not user:
        raise HTTPException(status_code=401, detail="E-posta veya şifre hatalı!")

    if not auth.verify_password(login_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="E-posta veya şifre hatalı!")

    if not getattr(user, "is_active", True):
        raise HTTPException(status_code=403, detail="Hesabınız yönetici tarafından askıya alınmıştır! Lütfen destek ile iletişime geçin.")

    token = auth.create_access_token({"sub": str(user.id), "email": user.email})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "is_admin": getattr(user, "is_admin", False),
            "is_active": getattr(user, "is_active", True)
        }
    }


@app.get("/api/auth/me", tags=["Kimlik Doğrulama"])
def get_me(current_user: models.User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "full_name": current_user.full_name,
        "email": current_user.email,
        "is_admin": getattr(current_user, "is_admin", False),
        "is_active": getattr(current_user, "is_active", True),
        "created_at": current_user.created_at
    }


# --- HEDEFLER (GOALS) API ---

def format_goal_response(goal: models.Goal) -> schemas.GoalResponse:
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

@app.get("/api/goals", response_model=schemas.GoalsSummaryResponse, tags=["Hedefler"])
def list_user_goals(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
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

@app.post("/api/goals", response_model=schemas.GoalResponse, tags=["Hedefler"])
def create_user_goal(
    goal_data: schemas.GoalCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
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

@app.post("/api/goals/{goal_id}/deposit", response_model=schemas.GoalResponse, tags=["Hedefler"])
def deposit_to_goal(
    goal_id: int,
    deposit: schemas.GoalDeposit,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
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

@app.delete("/api/goals/{goal_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Hedefler"])
def delete_goal(
    goal_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    goal = db.query(models.Goal).filter(
        models.Goal.id == goal_id,
        models.Goal.user_id == current_user.id
    ).first()
    
    if not goal:
        raise HTTPException(status_code=404, detail="Hedef bulunamadı!")
        
    db.delete(goal)
    db.commit()
    return None


# --- YÖNETİCİ (ADMIN) PANELİ API'LERİ ---
from auth import get_current_admin_user

@app.get("/api/admin/stats", response_model=schemas.AdminStatsResponse, tags=["Yönetici Paneli"])
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

@app.get("/api/admin/users", response_model=List[schemas.AdminUserItem], tags=["Yönetici Paneli"])
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

@app.post("/api/admin/users/{user_id}/toggle-admin", tags=["Yönetici Paneli"])
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

@app.post("/api/admin/users/{user_id}/role", tags=["Yönetici Paneli"])
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

@app.post("/api/admin/users/{user_id}/toggle-active", tags=["Yönetici Paneli"])
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

@app.delete("/api/admin/users/{user_id}", tags=["Yönetici Paneli"])
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

@app.get("/api/admin/system-health", tags=["Yönetici Paneli"])
def get_system_health(
    db: Session = Depends(get_db),
    admin: models.User = Depends(get_current_admin_user)
):
    """Sistem bileşenlerinin canlılık ve sağlık durumunu denetler."""
    import ai_service
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



