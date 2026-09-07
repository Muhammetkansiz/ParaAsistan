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
    currency: Optional[str] = "TRY"
    original_amount: Optional[float] = None
    exchange_rate: Optional[float] = 1.0

class TransactionCreate(TransactionBase):
    date: Optional[datetime] = None 
    repeat_months: Optional[int] = Field(1, ge=1, le=60, description="Kaç ay tekrarlanacağı (1 = tek seferlik)") 

class TransactionResponse(TransactionBase):
    id: int
    date: datetime
    currency: str = "TRY"
    original_amount: Optional[float] = None
    exchange_rate: Optional[float] = 1.0
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

class GoalCreate(BaseModel):
    title: str = Field(..., description="Hedef başlığı (örn: MacBook Pro)")
    target_amount: float = Field(..., gt=0, description="Hedef tutar")
    current_amount: Optional[float] = Field(0.0, ge=0, description="Mevcut birikim")
    target_date: Optional[datetime] = None
    category: Optional[str] = "Genel"
    icon: Optional[str] = "flag"
    color: Optional[str] = "#1a237e"

class GoalDeposit(BaseModel):
    amount: float = Field(..., gt=0, description="Eklenecek birikim tutarı")

class GoalResponse(BaseModel):
    id: int
    user_id: int
    title: str
    target_amount: float
    current_amount: float
    remaining_amount: float
    percentage: float
    target_date: Optional[datetime] = None
    remaining_days: Optional[int] = None
    category: str
    icon: str
    color: str
    status: str
    created_at: datetime
    class Config:
        from_attributes = True

class GoalsSummaryResponse(BaseModel):
    total_saved: float
    total_target: float
    overall_percentage: float
    active_goals_count: int
    completed_goals_count: int
    goals: List[GoalResponse]