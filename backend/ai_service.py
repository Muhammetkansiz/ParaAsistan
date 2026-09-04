# backend/ai_service.py
# ParaAsistan - Google Gemini Flash Kişisel Finans Danışmanı

import os
import json
import re
import datetime
import urllib.request
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
import models

# 1. .env Dosyasından API Anahtarını Yükle:
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")


# 2. Veritabanından Kullanıcının Gerçek Finansal Durumunu Çeken Fonksiyon:
def get_user_financial_context(db: Session) -> dict:
    now = datetime.datetime.now()
    
    income = db.query(func.sum(models.Transaction.amount)).filter(models.Transaction.type == "income").scalar() or 0.0
    expense = db.query(func.sum(models.Transaction.amount)).filter(models.Transaction.type == "expense").scalar() or 0.0
    balance = income - expense
    
    budgets = db.query(models.Budget).all()
    budget_list = []
    for b in budgets:
        spent = db.query(func.sum(models.Transaction.amount)).filter(
            models.Transaction.type == "expense",
            models.Transaction.category == b.category,
            extract('year', models.Transaction.date) == now.year, extract('month', models.Transaction.date) == now.month
        ).scalar() or 0.0
        
        budget_list.append({
            "category": b.category,
            "limit": b.monthly_limit,
            "spent": spent,
            "remaining": b.monthly_limit - spent
        })
        
    return {
        "balance": balance,
        "income": income,
        "expense": expense,
        "budgets": budget_list
    }


# 3. Gemini ile Akıllı Finansal Değerlendirme Yapan Ana Fonksiyon:
async def ask_financial_advisor(user_message: str, db: Session) -> dict:
    context_data = get_user_financial_context(db)
    
    budget_lines = []
    for b in context_data["budgets"]:
        budget_lines.append(f"- {b['category']}: Limit {b['limit']:,.0f} TL, Kalan {b['remaining']:,.0f} TL")
    budget_str = "\n".join(budget_lines) if budget_lines else "Tanımlı kategori bütçesi bulunmuyor."

    system_prompt = f"""Sen 'ParaAsistan' adında sade, net, samimi ve doğrudan sonuca odaklanan bir Finans Danışmanısın.

KULLANICININ ANLIK VERİTABANI DURUMU:
- Net Bakiye: {context_data['balance']:,.0f} TL
- Bu Ayki Toplam Harcama: {context_data['expense']:,.0f} TL
KATEGORİ BÜTÇELERİ:
{budget_str}

ÇOK KATI KURALLAR:
1. CEVABIN EN FAZLA 2 VEYA 3 KISA CÜMLE OLSUN. Asla uzun paragraflar yazma.
2. Doğrudan net cevap ver: Alabilir mi, almamalı mı ve bütçeyi nasıl etkiler?
3. Samimi, modern ve sade bir Türkçe kullan.
4. Yanıtını MUTLAKA ve SADECE aşağıdaki JSON formatında oluştur:

```json
{{
    "reply": "Maksimum 2-3 cümlelik çok sade ve net tavsiye mesajın.",
    "impact": {{
        "product_name": "Tespit edilen ürün/harcama adı",
        "price": 5000.0,
        "category": "İlgili kategori adı",
        "is_budget_exceeded": true,
        "ai_suggestion": "Tek cümlelik kısa altın tavsiye özeti"
    }}
}}
```"""

    if not GEMINI_API_KEY:
        numbers = re.findall(r"\d+", user_message)
        est_price = float(numbers[0]) if numbers else 3000.0
        exceeded = est_price > context_data["balance"]

        return {
            "reply": f"Mevcut bakiyeniz {context_data['balance']:,.0f} ₺. Bu harcama {'bütçenize uygun görünüyor, rahatlıkla yapabilirsiniz.' if not exceeded else 'bakiyenizi aşıyor, ertelemenizi öneririm.'}",
            "impact": {
                "product_name": "Planlanan Alışveriş",
                "price": est_price,
                "category": "Alışveriş",
                "is_budget_exceeded": exceeded,
                "ai_suggestion": "Bütçe dengenizi koruyarak hareket edin."
            }
        }

    candidate_models = ["gemini-3.5-flash", "gemini-3-flash-preview", "gemini-3.5-flash-lite"]

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": f"{system_prompt}\n\nKULLANICI: {user_message}"}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.3,
            "responseMimeType": "application/json"
        }
    }

    for model_name in candidate_models:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            
            with urllib.request.urlopen(req, timeout=12) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                raw_text = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
                
                if raw_text.startswith("```json"):
                    raw_text = raw_text.split("```json")[1].split("```")[0].strip()
                elif raw_text.startswith("```"):
                    raw_text = raw_text.split("```")[1].split("```")[0].strip()
                    
                return json.loads(raw_text)

        except Exception as e:
            continue

    return {
        "reply": "Şu anda yanıt üretilemedi, lütfen tekrar deneyin.",
        "impact": {}
    }
