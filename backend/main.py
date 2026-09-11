from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from init_db import init_db
from routers import (
    auth as auth_router,
    ai as ai_router,
    transactions as transactions_router,
    budgets as budgets_router,
    goals as goals_router,
    analytics as analytics_router,
    admin as admin_router,
    currency as currency_router
)

# 🚀 Veritabanı ve varsayılan verileri hazırla
init_db()

app = FastAPI(
    title="ParaAsistan API",
    description="Akıllı Finans ve Bütçe Yönetimi API'si",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_origin_regex=".*",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 🔌 Modüler Router'ları sisteme dahil et
app.include_router(auth_router.router)
app.include_router(ai_router.router)
app.include_router(transactions_router.router)
app.include_router(budgets_router.router)
app.include_router(goals_router.router)
app.include_router(analytics_router.router)
app.include_router(admin_router.router)
app.include_router(currency_router.router)


@app.get("/api/health", tags=["Sistem"])
def health_check():
    return {"status": "ok", "message": "ParaAsistan API sorunsuz çalışıyor"}
