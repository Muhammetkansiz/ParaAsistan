from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

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


from pydantic import BaseModel, Field, field_validator
import re

from email_validator import validate_email, EmailNotValidError, EmailUndeliverableError

class UserCreate(BaseModel):
    full_name: str
    email: str
    password: str

    @field_validator("full_name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        name = v.strip()
        if len(name) < 2:
            raise ValueError("Ad Soyad en az 2 karakter olmalıdır!")
        if any(char.isdigit() for char in name):
            raise ValueError("Ad Soyad alanında sayı veya rakam kullanılamaz!")
        if not re.match(r"^[a-zA-ZçÇğĞıİöÖşŞüÜ\s\.\-']+$", name):
            raise ValueError("Ad Soyad yalnızca harflerden oluşmalıdır!")
        return name

    @field_validator("email")
    @classmethod
    def validate_email_address(cls, v: str) -> str:
        raw_email = v.strip()
        if not raw_email:
            raise ValueError("E-posta adresi boş bırakılamaz!")
        try:
            # check_deliverability=True: Alan adının (domain) gerçek bir mail sunucusu (MX) olup olmadığını denetler
            validated = validate_email(raw_email, check_deliverability=True)
            return validated.normalized
        except EmailUndeliverableError:
            raise ValueError("Girdiğiniz e-posta alan adına ait aktif bir posta sunucusu bulunamadı! Lütfen geçerli bir e-posta adresi giriniz.")
        except EmailNotValidError as e:
            raise ValueError(f"Geçersiz e-posta formatı: {str(e)}")

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Şifre en az 6 karakter olmalıdır!")
        if not re.search(r"[a-zA-ZçÇğĞıİöÖşŞüÜ]", v) or not re.search(r"\d", v):
            raise ValueError("Şifreniz en az bir harf ve bir rakam içermelidir!")
        return v

class UserResponse(BaseModel):
    id: int
    full_name: str
    email: str
    is_admin: bool = False
    is_active: bool = True
    created_at: datetime
    class Config:
        from_attributes = True

class AdminUserItem(BaseModel):
    id: int
    full_name: str
    email: str
    is_admin: bool
    is_active: bool
    created_at: datetime
    transactions_count: int = 0
    total_spent: float = 0.0
    total_income: float = 0.0

class UserRoleUpdate(BaseModel):
    role: str

class RecurringTransactionCreate(BaseModel):
    type: str = Field(..., description="'expense' veya 'income'")
    amount: float = Field(..., gt=0, description="Düzenli işlem tutarı")
    category: str = Field(..., description="Kategori adı")
    description: Optional[str] = None
    day_of_month: int = Field(1, ge=1, le=31, description="Ayın günü (1-31)")
    total_months: int = Field(12, ge=1, description="Toplam ay süresi (örn: 12 veya 999)")

class RecurringTransactionUpdate(BaseModel):
    type: Optional[str] = None
    amount: Optional[float] = Field(None, gt=0)
    category: Optional[str] = None
    description: Optional[str] = None
    day_of_month: Optional[int] = Field(None, ge=1, le=31)
    total_months: Optional[int] = Field(None, ge=1)
    is_active: Optional[int] = None

class RecurringTransactionResponse(BaseModel):
    id: int
    user_id: int
    type: str
    amount: float
    category: str
    description: Optional[str] = None
    day_of_month: int
    total_months: int
    paid_months: int
    last_payment_date: Optional[datetime] = None
    is_active: int
    created_at: datetime
    class Config:
        from_attributes = True


class AdminStatsResponse(BaseModel):
    total_users: int
    total_transactions: int
    total_volume: float
    total_goals: int
    total_chat_messages: int = 0  # Geriye dönük uyumluluk için
    total_ai_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_ai_requests: int = 0
    new_users_last_7_days: int

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