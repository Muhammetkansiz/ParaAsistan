from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime

AllowedCategories = Literal[
    "Market", 
    "Kira", 
    "Ulaşım", 
    "Fatura", 
    "Teknoloji", 
    "Eğlence", 
    "Maaş", 
    "Ek Gelir",
    "Yatırım",
    "Sağlık",
    "Eğitim",
    "Diğer"
]

class TransactionBase(BaseModel):
    type: str = Field(..., description="'income' veya 'expense'")
    amount: float = Field(..., gt=0)
    category: str = Field(..., description="Kategori adı")
    description: Optional[str] = None

class TransactionCreate(TransactionBase):
    date: Optional[datetime] = None 

class TransactionResponse(TransactionBase):
    id: int
    date: datetime
    class Config:
        from_attributes = True

class SummaryResponse(BaseModel):
    total_income: float
    total_expense: float  
    net_balance: float    
    savings_rate: float



class BudgetBase(BaseModel):
    category: str
    monthly_limit: float = Field(..., gt=0)
    month: Optional[str] = None

class BudgetCreate(BudgetBase):
    pass

class BudgetProgressResponse(BaseModel):
    id: Optional[int] = None
    category: str
    monthly_limit: float
    spent: float
    remaining: float
    percentage: float
    status: str # "on_track" veya "exceeded"

class BudgetSummaryResponse(BaseModel):
    total_budget: float
    total_spent: float
    remaining: float
    percentage: float


class UserCreate(BaseModel):
    full_name: str
    email: str
    password: str

class UserResponse(BaseModel):
    id: int
    full_name: str
    email: str
    created_at: datetime
    class Config:
        from_attributes = True

class UserLogin(BaseModel):
    email: str
    password: str

class CategoryResponse(BaseModel):
    id: int
    name: str
    type: str
    icon: str
    color: str
    class Config:
        from_attributes = True