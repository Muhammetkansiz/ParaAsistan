from sqlalchemy import Column, Integer, String, Float, DateTime, Text
from database import Base
import datetime

class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True, index=True)
    type = Column(String, nullable=False)              
    amount = Column(Float, nullable=False)             
    category = Column(String, nullable=False)    
    description = Column(String, nullable=True)        
    date = Column(DateTime, default=datetime.datetime.utcnow)


class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False) 
    type = Column(String, nullable=False)              
    icon = Column(String, default="payments")       
    color = Column(String, default="#1a237e")          


class Budget(Base):
    __tablename__ = "budgets"
    id = Column(Integer, primary_key=True, index=True)
    category = Column(String, nullable=False)
    monthly_limit = Column(Float, nullable=False)
    month = Column(String, nullable=True)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True, index=True)
    role = Column(String, nullable=False) 
    content = Column(Text, nullable=False)            
    created_at = Column(DateTime, default=datetime.datetime.utcnow) 