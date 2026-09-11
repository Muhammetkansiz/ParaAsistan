# backend/services/recurring_service.py
# ParaAsistan - Düzenli & Tekrarlayan Harcama İşletim Servisi

import datetime
import calendar
from sqlalchemy.orm import Session
import models

def process_recurring_transactions(db: Session, user_id: int):
    """
    Günü gelmiş olan tekrarlayan ödemeleri (taksit, abonelik vb.) kontrol eder
    ve günü geldiyse transactions tablosuna otomatik olarak ekler.
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
