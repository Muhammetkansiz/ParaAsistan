from fastapi import APIRouter
import currency_service

router = APIRouter(prefix="/api/currency", tags=["Döviz & Kurlar"])


@router.get("/rates")
def get_exchange_rates():
    """Frankfurter (Avrupa Merkez Bankası) üzerinden güncel canlı döviz kurlarını döner."""
    return currency_service.get_live_rates()
