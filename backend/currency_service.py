# backend/currency_service.py
# ParaAsistan - Frankfurter / Avrupa Merkez Bankası (ECB) Canlı Döviz Servisi

import urllib.request
import json
import time

# 30 dakika önbellek (Cache): Sürekli dış ağa istek atmayı önler, ışık hızında yanıt verir
CACHE = {
    "rates": {},
    "last_updated": 0
}

def get_live_rates() -> dict:
    """
    Avrupa Merkez Bankası (ECB) destekli Frankfurter API üzerinden
    USD, EUR, GBP ve TRY paritelerini çeker ve 30 dakika önbellekte tutar.
    """
    now = time.time()
    # 30 dakika (1800 saniye) geçmediyse önbellekten dön:
    if CACHE["rates"] and (now - CACHE["last_updated"] < 1800):
        return CACHE["rates"]

    try:
        url = "https://api.frankfurter.dev/v1/latest?base=USD&symbols=TRY,EUR,GBP"
        req = urllib.request.Request(url, headers={"User-Agent": "ParaAsistan/1.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
            
            usd_try = float(data["rates"]["TRY"])
            eur_usd = 1.0 / float(data["rates"]["EUR"])
            eur_try = eur_usd * usd_try
            gbp_usd = 1.0 / float(data["rates"]["GBP"])
            gbp_try = gbp_usd * usd_try

            rates = {
                "TRY": 1.0,
                "USD": round(usd_try, 2),
                "EUR": round(eur_try, 2),
                "GBP": round(gbp_try, 2),
                "date": data.get("date", "")
            }
            CACHE["rates"] = rates
            CACHE["last_updated"] = now
            return rates

    except Exception as e:
        print("[Currency Service Warning] Canlı kur çekilemedi, yedek kur devrede:", e)
        # Eğer internet kesintisi veya geçici API sorunu olursa yedek güvenli kurlar devrede:
        return {
            "TRY": 1.0,
            "USD": 48.45,
            "EUR": 56.30,
            "GBP": 65.50,
            "date": "2026-09-07"
        }
