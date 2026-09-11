# backend/routers/ai.py
# ParaAsistan - Yapay Zeka & Belge Tarama (AI) Router Modülü

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database import get_db
import models
from auth import get_current_user
import ai_service
import statement_service

router = APIRouter(prefix="/api/ai", tags=["Yapay Zeka"])

class ChatRequest(BaseModel):
    message: str


@router.post("/chat")
async def chat_with_ai(
    req: ChatRequest, 
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Kullanıcının finansal danışman yapay zeka ile sohbet etmesini sağlar."""
    result = await ai_service.ask_financial_advisor(req.message, db, user_id=current_user.id)
    return result


@router.get("/panel-context")
def get_ai_panel_context(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Yapay zeka asistan sayfasındaki sağ panel için canlı bütçe özetini döner."""
    return ai_service.get_panel_context(db, user_id=current_user.id)


@router.get("/daily-briefing")
async def get_daily_briefing(
    force_refresh: bool = Query(False, description="Zorla yenileme bayrağı"),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Kullanıcının gerçek finansal verilerini analiz edip kişiselleştirilmiş günlük AI brifingi döner."""
    briefing = await ai_service.generate_daily_briefing(db, current_user.id, force_refresh=force_refresh)
    return briefing


@router.post("/scan-receipt")
async def scan_receipt(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """Kullanıcının yüklediği fiş, fatura veya banka ekstresini (Görsel, PDF, CSV) analiz eder."""
    allowed_types = ["image/", "application/pdf", "text/csv", "application/csv", "text/plain", "application/vnd.ms-excel"]
    fname = (file.filename or "").lower()
    is_valid_type = any(file.content_type and file.content_type.startswith(t) for t in allowed_types) or fname.endswith((".csv", ".pdf", ".png", ".jpg", ".jpeg", ".webp"))

    if not is_valid_type:
        raise HTTPException(
            status_code=400, 
            detail="Lütfen geçerli bir fiş/dekont görseli (JPEG/PNG), banka ekstresi (PDF) veya CSV dökümü yükleyin."
        )

    contents = await file.read()
    doc_data = await statement_service.parse_statement_with_gemini(contents, file.content_type or "application/octet-stream", filename=file.filename or "")
    
    # Token kullanımını kaydet
    if "usage_metadata" in doc_data and doc_data["usage_metadata"]:
        feature_name = "statement_scan" if doc_data.get("is_statement") else "receipt_scan"
        model_name = doc_data.get("model_used", "gemini-3.6-flash")
        ai_service.log_token_usage(db, current_user.id, model_name, feature_name, doc_data.get("usage_metadata"))

    # Guardrails: Eğer finansal evrak harici uygunsuz bir belge tespit edildiyse reddet
    is_valid = doc_data.get("is_valid_document", True)
    if not doc_data.get("is_statement"):
        is_valid = is_valid and doc_data.get("is_valid_receipt", True)
    if not is_valid:
        raise HTTPException(
            status_code=400, 
            detail=doc_data.get("error", "Yüklenen belge geçerli bir fiş veya banka ekstresi değildir. Güvenlik politikası gereği kimlik veya kart belgeleri işlenemez.")
        )

    return doc_data
