from fastapi import FastAPI, Depends, HTTPException, Query, status, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func, extract, text
from typing import List, Optional
import datetime
import calendar
from database import engine, Base, get_db, SessionLocal
import models
import schemas
from auth import get_current_user
import currency_service

# 🚀 Tabloları veritabanında otomatik oluştur (yoksa)
Base.metadata.create_all(bind=engine)

# 🔄 Otomatik Veritabanı Kolon Eşitleme (Migration)
def migrate_db_columns():
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS currency VARCHAR DEFAULT 'TRY';"))
            conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS original_amount FLOAT;"))
            conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS exchange_rate FLOAT DEFAULT 1.0;"))
        print("✅ Veritabanı para birimi kolonları başarıyla eşitlendi.")
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
        last_date = rule.last_payment_date or rule.created_at
        
        # Gelecek taksitin yıl ve ayı:
        total_months = last_date.year * 12 + (last_date.month - 1) + 1
        next_year = total_months // 12
        next_month = (total_months % 12) + 1
        
        max_days = calendar.monthrange(next_year, next_month)[1]
        next_day = min(rule.day_of_month, max_days)
        next_payment_date = datetime.datetime(next_year, next_month, next_day, last_date.hour, last_date.minute, last_date.second)
        
        # Eğer bir sonraki taksit günü geldiyse veya geçtiyse:
        if now >= next_payment_date:
            rule.paid_months += 1
            rule.last_payment_date = next_payment_date
            
            desc = f"{rule.description} ({rule.paid_months}/{rule.total_months})"
            new_tx = models.Transaction(
                user_id=user_id,
                type=rule.type,
                amount=rule.amount,
                category=rule.category,
                description=desc,
                date=next_payment_date
            )
            db.add(new_tx)
            
            if rule.paid_months >= rule.total_months:
                rule.is_active = 0
                
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



@app.get("/api/recurring-transactions", tags=["İşlemler"])
def get_recurring_transactions(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    process_recurring_transactions(db, current_user.id)
    return db.query(models.RecurringTransaction).filter(
        models.RecurringTransaction.user_id == current_user.id
    ).order_by(models.RecurringTransaction.created_at.desc()).all()


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


@app.post("/api/ai/scan-receipt", tags=["Yapay Zeka"])
async def scan_receipt(
    file: UploadFile = File(...),
    current_user: models.User = Depends(get_current_user)
):
    """Kullanıcının yüklediği fiş/fatura görselini Gemini Vision ile tarar ve yapılandırılmış JSON döner."""
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Lütfen geçerli bir görsel dosyası (JPEG, PNG, WebP) yükleyin.")

    contents = await file.read()
    receipt_data = await ai_service.scan_receipt_with_gemini(contents, file.content_type)
    return receipt_data



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

    token = auth.create_access_token({"sub": str(user.id), "email": user.email})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "full_name": user.full_name,
            "email": user.email
        }
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

