from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Boolean
from database import Base
import datetime

class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=True)
    type = Column(String, index=True, nullable=False)              
    amount = Column(Float, nullable=False)             
    category = Column(String, index=True, nullable=False)    
    description = Column(String, nullable=True)        
    date = Column(DateTime, index=True, default=datetime.datetime.utcnow)
    currency = Column(String, default="TRY")
    original_amount = Column(Float, nullable=True)
    exchange_rate = Column(Float, default=1.0)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)                        
    email = Column(String, unique=True, index=True, nullable=False)    
    hashed_password = Column(String, nullable=False)               
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    is_admin = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)

class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False) 
    type = Column(String, nullable=False)              
    icon = Column(String, default="payments")       
    color = Column(String, default="#1a237e")          


class Budget(Base):
    __tablename__ = "user_budgets"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=True)
    category = Column(String, nullable=False)
    monthly_limit = Column(Float, nullable=False)
    month = Column(String, nullable=True)


class AITokenUsage(Base):
    __tablename__ = "ai_token_usage"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=True)
    model = Column(String, nullable=False)  # 'gemini-2.5-flash', 'gemini-3.6-flash' vb.
    feature = Column(String, nullable=False)  # 'chat', 'receipt_scan', 'daily_briefing'
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow) 


class RecurringTransaction(Base):
    __tablename__ = "recurring_transactions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    type = Column(String, nullable=False)  # 'expense' veya 'income'
    amount = Column(Float, nullable=False)
    category = Column(String, nullable=False)
    description = Column(String, nullable=True)
    day_of_month = Column(Integer, default=1)  # Ayın hangi günü (1-31)
    total_months = Column(Integer, nullable=False)  # Toplam ay sayısı (örn: 6)
    paid_months = Column(Integer, default=0)  # Ödenen ay sayısı
    last_payment_date = Column(DateTime, nullable=True, default=None)
    is_active = Column(Integer, default=1)  # 1: Aktif, 0: Tamamlandı veya iptal
    created_at = Column(DateTime, default=datetime.datetime.utcnow) 


class Goal(Base):
    __tablename__ = "user_goals"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=False)
    title = Column(String, nullable=False)
    target_amount = Column(Float, nullable=False)
    current_amount = Column(Float, default=0.0)
    target_date = Column(DateTime, nullable=True)
    category = Column(String, default="Genel")
    icon = Column(String, default="flag")
    color = Column(String, default="#1a237e")
    status = Column(String, default="in_progress")  # 'in_progress' veya 'completed'
    created_at = Column(DateTime, default=datetime.datetime.utcnow) 