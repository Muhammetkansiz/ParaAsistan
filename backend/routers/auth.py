# backend/routers/auth.py
# ParaAsistan - Kimlik Doğrulama (Auth) Router Modülü

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
import models
import schemas
import auth
from auth import get_current_user

router = APIRouter(prefix="/api/auth", tags=["Kimlik Doğrulama"])

@router.post("/register", response_model=schemas.UserResponse)
def register(user_data: schemas.UserCreate, db: Session = Depends(get_db)):
    """Yeni kullanıcı kaydı oluşturur."""
    name = user_data.full_name.strip()
    if any(char.isdigit() for char in name):
        raise HTTPException(status_code=400, detail="Ad Soyad alanında sayı veya rakam kullanılamaz!")
    import re
    if not re.match(r"^[a-zA-ZçÇğĞıİöÖşŞüÜ\s\.\-']+$", name):
        raise HTTPException(status_code=400, detail="Ad Soyad yalnızca harflerden oluşmalıdır!")

    # E-posta Doğrulama (email-validator)
    try:
        from email_validator import validate_email, EmailNotValidError, EmailUndeliverableError
        validated = validate_email(user_data.email.strip(), check_deliverability=True)
        user_email = validated.normalized
    except EmailUndeliverableError:
        raise HTTPException(
            status_code=400, 
            detail="Girdiğiniz e-posta alan adına ait aktif bir posta sunucusu bulunamadı! Lütfen geçerli bir e-posta adresi giriniz."
        )
    except EmailNotValidError:
        raise HTTPException(
            status_code=400, 
            detail="Geçersiz e-posta formatı! Lütfen e-posta adresinizi kontrol ediniz."
        )

    existing_user = db.query(models.User).filter(models.User.email == user_email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Bu e-posta adresi zaten kayıtlı!")

    hashed_pwd = auth.hash_password(user_data.password)

    new_user = models.User(
        full_name=user_data.full_name,
        email=user_email,
        hashed_password=hashed_pwd
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@router.post("/login")
def login(login_data: schemas.UserLogin, db: Session = Depends(get_db)):
    """Kullanıcı girişini doğrular ve JWT erişim bileti (access token) üretir."""
    user = db.query(models.User).filter(models.User.email == login_data.email).first()
    if not user:
        raise HTTPException(status_code=401, detail="E-posta veya şifre hatalı!")

    if not auth.verify_password(login_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="E-posta veya şifre hatalı!")

    if not getattr(user, "is_active", True):
        raise HTTPException(status_code=403, detail="Hesabınız yönetici tarafından askıya alınmıştır! Lütfen destek ile iletişime geçin.")

    token = auth.create_access_token({"sub": str(user.id), "email": user.email})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "full_name": user.full_name,
            "email": user.email,
            "is_admin": getattr(user, "is_admin", False),
            "is_active": getattr(user, "is_active", True)
        }
    }


@router.get("/me")
def get_me(current_user: models.User = Depends(get_current_user)):
    """O an giriş yapmış kullanıcının profil ve yetki bilgilerini döner."""
    return {
        "id": current_user.id,
        "full_name": current_user.full_name,
        "email": current_user.email,
        "is_admin": getattr(current_user, "is_admin", False),
        "is_active": getattr(current_user, "is_active", True),
        "created_at": current_user.created_at
    }
