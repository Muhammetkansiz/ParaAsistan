from fastapi import FastAPI, Depends, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from typing import List, Optional
import datetime
from database import engine, Base, get_db
import models
import schemas
from auth import get_current_user



Base.metadata.create_all(bind=engine)

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


@app.post("/api/transactions", tags=["İşlemler"])
def create_transaction(
    transaction: schemas.TransactionCreate, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    tx_date = transaction.date if transaction.date else datetime.datetime.utcnow()
    db_tx = models.Transaction(
        user_id=current_user.id,
        type=transaction.type,
        amount=transaction.amount,
        category=transaction.category,
        description=transaction.description,
        date=tx_date
    )
    db.add(db_tx)
    db.commit()
    db.refresh(db_tx)
    return db_tx

@app.get("/api/transactions", response_model=List[schemas.TransactionResponse], tags=["İşlemler"])
def list_transactions(
    type: Optional[str] = Query(None, description="'income' veya 'expense' filtresi"),
    category: Optional[str] = Query(None, description="Kategori filtresi"),
    limit: int = 50,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Sadece giriş yapmış olan kullanıcının işlemlerini getir:
    query = db.query(models.Transaction).filter(models.Transaction.user_id == current_user.id)
    
    if type:
        query = query.filter(models.Transaction.type == type)
        
    if category:
        query = query.filter(models.Transaction.category == category)
    
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



@app.get("/api/analytics/summary", response_model=schemas.SummaryResponse, tags=["Analiz"])
def get_financial_summary(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
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
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # Son 6 ayı Türkçe isimleriyle hazırla
    turkish_months = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", 
                      "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
    
    now = datetime.datetime.now()
    months_data = []
    
    # Son 6 ayı geriye doğru hesapla
    for i in range(5, -1, -1):
        month_idx = (now.month - 1 - i) % 12
        year = now.year if (now.month - 1 - i) >= 0 else now.year - 1
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
        
        months_data.append({
            "month": month_name,
            "year": year,
            "income": round(inc, 2),
            "expense": round(exp, 2)
        })
        
    return months_data


@app.get("/api/analytics/category-spending", tags=["Analiz"])
def get_category_spending(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    now = datetime.datetime.now()
    results = db.query(
        models.Transaction.category,
        func.sum(models.Transaction.amount).label("total")
    ).filter(
        models.Transaction.type == "expense",
        models.Transaction.user_id == current_user.id,
        extract('year', models.Transaction.date) == now.year, 
        extract('month', models.Transaction.date) == now.month
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
        status="exceeded" if spent > db_budget.monthly_limit else "on_track"
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
            status="exceeded" if spent > b.monthly_limit else "on_track"
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
    total_spent = db.query(func.sum(models.Transaction.amount)).filter(
        models.Transaction.type == "expense",
        models.Transaction.user_id == current_user.id,
        extract('year', models.Transaction.date) == now.year, 
        extract('month', models.Transaction.date) == now.month
    ).scalar() or 0.0

    rem = total_budget - total_spent
    pct = round((total_spent / total_budget) * 100, 1) if total_budget > 0 else 0.0

    return schemas.BudgetSummaryResponse(
        total_budget=round(total_budget, 2),
        total_spent=round(total_spent, 2),
        remaining=round(rem, 2),
        percentage=pct
    )


import ai_service
from pydantic import BaseModel

class ChatRequest(BaseModel):
    message: str

@app.post("/api/ai/chat", tags=["Yapay Zeka"])
async def chat_with_ai(req: ChatRequest, db: Session = Depends(get_db)):
    result = await ai_service.ask_financial_advisor(req.message, db)
    return result


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

