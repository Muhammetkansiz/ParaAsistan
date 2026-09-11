# backend/services/analytics_service.py
# ParaAsistan - Finansal Analitik, Nakit Akışı ve Raporlama Servisi

import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
import models

def calculate_financial_summary(db: Session, user_id: int) -> dict:
    """
    Kullanıcının toplam gelir, gider, net bakiye ve tasarruf oranını hesaplar.
    """
    income = db.query(func.sum(models.Transaction.amount)).filter(
        models.Transaction.type == "income",
        models.Transaction.user_id == user_id
    ).scalar() or 0.0

    expense = db.query(func.sum(models.Transaction.amount)).filter(
        models.Transaction.type == "expense",
        models.Transaction.user_id == user_id
    ).scalar() or 0.0

    net = income - expense
    savings_rate = ((income - expense) / income * 100) if income > 0 else 0.0

    return {
        "total_income": round(income, 2),
        "total_expense": round(expense, 2),
        "net_balance": round(net, 2),
        "savings_rate": round(max(savings_rate, 0.0), 1)
    }


def calculate_monthly_cashflow(db: Session, user_id: int, period: str = "6months") -> list:
    """
    Seçilen döneme göre (aylık haftalık kırılım, 3 ay, 6 ay, yıllık, tümü)
    gelir ve gider hareketlerini hesaplar.
    """
    turkish_months = [
        "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", 
        "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"
    ]
    
    now = datetime.datetime.now()
    months_data = []

    # 1. "Bu Ay" seçildiyse son 4 haftalık (28 gün) hareketli kırılım göster
    if period == "month":
        for w in range(3, -1, -1):
            end_date = now - datetime.timedelta(days=w * 7)
            start_date = end_date - datetime.timedelta(days=6)
            s_dt = datetime.datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0)
            e_dt = datetime.datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59)
            s_abbr = turkish_months[start_date.month - 1][:3]
            e_abbr = turkish_months[end_date.month - 1][:3]
            label = f"{start_date.day}-{end_date.day} {s_abbr}" if start_date.month == end_date.month else f"{start_date.day} {s_abbr}-{end_date.day} {e_abbr}"

            inc = db.query(func.sum(models.Transaction.amount)).filter(
                models.Transaction.type == "income",
                models.Transaction.user_id == user_id,
                models.Transaction.date >= s_dt,
                models.Transaction.date <= e_dt
            ).scalar() or 0.0

            exp = db.query(func.sum(models.Transaction.amount)).filter(
                models.Transaction.type == "expense",
                models.Transaction.user_id == user_id,
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
        count = now.month
    elif period == "all":
        count = 12
    else:
        count = 6  # Varsayılan: Son 6 ay

    for i in range(count - 1, -1, -1):
        total_months = now.year * 12 + (now.month - 1) - i
        year = total_months // 12
        month_idx = total_months % 12
        month_num = month_idx + 1
        month_name = turkish_months[month_idx]

        inc = db.query(func.sum(models.Transaction.amount)).filter(
            models.Transaction.type == "income",
            models.Transaction.user_id == user_id,
            extract('year', models.Transaction.date) == year,
            extract('month', models.Transaction.date) == month_num
        ).scalar() or 0.0

        exp = db.query(func.sum(models.Transaction.amount)).filter(
            models.Transaction.type == "expense",
            models.Transaction.user_id == user_id,
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


def calculate_category_spending(db: Session, user_id: int, period: str = "month") -> list:
    """
    Seçilen döneme göre kullanıcının gider kategorisi harcama toplamlarını
    ve yüzdesel paylarını hesaplar, tutara göre azalan sıralar.
    """
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
        models.Transaction.user_id == user_id,
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

    data.sort(key=lambda x: x["amount"], reverse=True)
    return data
