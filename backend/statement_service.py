# backend/statement_service.py
# ParaAsistan - Banka & Kredi Kartı Ekstre Ayrıştırıcı (PDF, CSV, Görsel)

import io
import csv
import json
import base64
import re
import datetime
import urllib.request
from typing import List, Dict, Any, Optional
from guardrails import AIGuardrails
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

STANDARD_CATEGORIES = [
    "Market", "Ulaşım", "Teknoloji", "Eğlence", "Fatura",
    "Kira", "Sağlık", "Eğitim", "Giyim", "Maaş", "Yatırım", "Diğer"
]


def guess_category_from_description(desc: str) -> str:
    """Açıklamadaki anahtar kelimelere göre kategori tahmini yapar."""
    d = desc.lower()
    if any(k in d for k in ["migros", "bim", "a101", "sok", "şok", "carrefour", "market", "bakkal", "fırın", "gıda", "kasap", "manav"]):
        return "Market"
    if any(k in d for k in ["shell", "bp", "opet", "petrol", "benzin", "yakıt", "akaryakıt", "taksi", "uber", "marti", "bilet", "otobus", "metro", "ulasim", "ulaşım", "havayol", "thy", "pegasus"]):
        return "Ulaşım"
    if any(k in d for k in ["apple", "google", "vatan", "teknosa", "mediamarkt", "trendyol", "hepsiburada", "amazon", "teknoloji", "bilgisayar", "telefon"]):
        return "Teknoloji"
    if any(k in d for k in ["netflix", "spotify", "youtube", "sinema", "tiyatro", "oyun", "steam", "playstation", "pub", "bar", "kafe", "cafe", "kahve", "starbucks"]):
        return "Eğlence"
    if any(k in d for k in ["vodafone", "turkcell", "turk telekom", "enerjisa", "iski", "igdas", "igdaş", "elektrik", "su", "dogalgaz", "doğalgaz", "fatura", "internet", "d-smart", "digiturk"]):
        return "Fatura"
    if any(k in d for k in ["kira", "ev sahibi", "aidat", "apartman", "site"]):
        return "Kira"
    if any(k in d for k in ["eczane", "hastane", "klinik", "doktor", "dis", "diş", "saglik", "sağlık", "laboratuvar", "medikal"]):
        return "Sağlık"
    if any(k in d for k in ["zara", "h&m", "lc waikiki", "koton", "boyner", "defacto", "mango", "nike", "adidas", "giyim", "ayakkabı", "butik"]):
        return "Giyim"
    if any(k in d for k in ["okul", "universite", "üniversite", "kurs", "kitap", "kirtasiye", "kırtasiye", "egitim", "eğitim", "harç"]):
        return "Eğitim"
    if any(k in d for k in ["maas", "maaş", "ücret", "prim", "avans", "bordro"]):
        return "Maaş"
    if any(k in d for k in ["faiz", "temettu", "temettü", "hisse", "fon", "kripto", "binance", "btcturk", "paribu", "yatırım"]):
        return "Yatırım"
    return "Diğer"


def parse_csv_statement(content_bytes: bytes) -> Dict[str, Any]:
    """
    Kullanıcının yüklediği CSV banka ekstresini satır satır ayrıştırır.
    Farklı bankaların sütun formatlarına (virgül, noktalı virgül, tab) uyum sağlar.
    """
    try:
        # Kodlama tespiti (UTF-8, ISO-8859-9 / Windows-1254 Türkçe)
        try:
            text = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = content_bytes.decode("windows-1254", errors="replace")

        lines = [l for l in text.splitlines() if l.strip()]
        if not lines:
            return {"is_valid_document": False, "error": "CSV dosyası boş görünüyor."}

        # Delimiter tahmini (, ; veya \t)
        sample = "\n".join(lines[:5])
        dialect = csv.Sniffer().sniff(sample, delimiters=";,|\t")
        delimiter = dialect.delimiter
    except Exception:
        delimiter = ";" if ";" in lines[0] else ","

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = list(reader)

    if not rows or len(rows) < 2:
        return {"is_valid_document": False, "error": "CSV dosyasında yeterli veri satırı bulunamadı."}

    # Başlık satırını tespit et
    header = [str(c).lower().strip() for c in rows[0]]
    date_col = -1
    desc_col = -1
    amount_col = -1
    type_col = -1

    for idx, col in enumerate(header):
        if any(k in col for k in ["tarih", "date", "işlem tarihi", "islem tarihi"]):
            date_col = idx
        elif any(k in col for k in ["açıklama", "aciklama", "description", "işlem", "islem", "detay"]):
            desc_col = idx
        elif any(k in col for k in ["tutar", "amount", "borç", "alacak", "hareket"]):
            if amount_col == -1:
                amount_col = idx
        elif any(k in col for k in ["tür", "tur", "type", "b/a", "işlem türü"]):
            type_col = idx

    # Eğer başlık bulunamadıysa ilk 3 sütunu varsay: Tarih, Açıklama, Tutar
    if date_col == -1: date_col = 0
    if desc_col == -1: desc_col = 1 if len(rows[0]) > 1 else 0
    if amount_col == -1: amount_col = 2 if len(rows[0]) > 2 else 1

    transactions = []
    total_expense = 0.0
    total_income = 0.0

    today_str = datetime.datetime.now().strftime("%Y-%m-%d")

    for row in rows[1:]:
        if not row or len(row) <= max(date_col, desc_col, amount_col):
            continue

        raw_date = row[date_col].strip()
        raw_desc = row[desc_col].strip()
        raw_amount = row[amount_col].strip()

        # Tarihi ayrıştır (GG.AA.YYYY veya YYYY-MM-DD)
        parsed_date = today_str
        date_match = re.search(r'(\d{1,4})[./-](\d{1,2})[./-](\d{2,4})', raw_date)
        if date_match:
            parts = [int(p) for p in date_match.groups()]
            if parts[0] > 1900:  # YYYY-MM-DD
                parsed_date = f"{parts[0]:04d}-{parts[1]:02d}-{parts[2]:02d}"
            else:  # DD.MM.YYYY
                year_val = parts[2]
                if year_val < 100:
                    year_val += 2000
                parsed_date = f"{year_val:04d}-{parts[1]:02d}-{parts[0]:02d}"

        # Tutarı temizle ve sayıya dönüştür
        # "1.250,50 TL" -> 1250.50
        clean_amount_str = re.sub(r'[^\d,.-]', '', raw_amount)
        if "." in clean_amount_str and "," in clean_amount_str:
            clean_amount_str = clean_amount_str.replace(".", "").replace(",", ".")
        elif "," in clean_amount_str:
            clean_amount_str = clean_amount_str.replace(",", ".")

        try:
            val = float(clean_amount_str)
        except ValueError:
            continue

        if val == 0:
            continue

        tx_type = "income" if val > 0 else "expense"
        abs_amount = round(abs(val), 2)

        # Eğer sütunda borç/alacak varsa
        if type_col != -1 and len(row) > type_col:
            raw_type = row[type_col].lower()
            if any(k in raw_type for k in ["gelir", "alacak", "cr", "credit", "artı"]):
                tx_type = "income"
            elif any(k in raw_type for k in ["gider", "borç", "dr", "debit", "eksi"]):
                tx_type = "expense"

        if tx_type == "expense":
            total_expense += abs_amount
        else:
            total_income += abs_amount

        category = "Maaş" if tx_type == "income" else guess_category_from_description(raw_desc)
        safe_desc = AIGuardrails.mask_sensitive_data(raw_desc or "Banka İşlemi")

        transactions.append({
            "date": parsed_date,
            "description": safe_desc,
            "amount": abs_amount,
            "type": tx_type,
            "category": category,
            "currency": "TRY"
        })

    if not transactions:
        return {"is_valid_document": False, "error": "CSV dosyasında geçerli işlem satırı okunamadı."}

    return {
        "is_valid_document": True,
        "is_statement": True,
        "bank_name": "CSV Banka Ekstresi",
        "summary_text": f"CSV ekstreniz incelendi. Toplam {len(transactions)} işlem tespit edildi.",
        "total_expense": round(total_expense, 2),
        "total_income": round(total_income, 2),
        "currency": "TRY",
        "transactions": transactions
    }


async def parse_statement_with_gemini(file_bytes: bytes, mime_type: str, filename: str = "") -> Dict[str, Any]:
    """
    PDF, Görsel veya Excel/CSV ekstrelerini Google Gemini Vision/Document API ile analiz eder.
    Hem tekil fişleri hem de çok satırlı banka ekstrelerini ayırt edebilen evrensel motor.
    """
    fname = (filename or "").lower()

    # 1. Dosya CSV ise yerel olarak saniyeler içinde hatasız ayrıştır
    if (mime_type and any(c in mime_type for c in ["csv", "excel"])) or fname.endswith(".csv"):
        return parse_csv_statement(file_bytes)

    # 2. MIME Tipini doğrula ve düzelt
    if not mime_type or mime_type == "application/octet-stream":
        ext = os.path.splitext(fname)[1]
        if ext in [".jpg", ".jpeg"]:
            mime_type = "image/jpeg"
        elif ext == ".png":
            mime_type = "image/png"
        elif ext == ".webp":
            mime_type = "image/webp"
        elif ext == ".pdf":
            mime_type = "application/pdf"
        elif ext == ".csv":
            mime_type = "text/csv"
        else:
            mime_type = "image/jpeg"

    # PDF veya Görsel ise Gemini'ye gönder
    base64_data = base64.b64encode(file_bytes).decode("utf-8")
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    current_year = datetime.datetime.now().year

    prompt = f"""Sen uzman bir Türk Finans Belgesi, Banka Ekstresi, Hesap Özeti ve Fiş/Fatura Analiz Asistanısın.
Sana iletilen belgeyi (PDF, Fotoğraf, Ekran Görüntüsü) satır satır son derece titizlikle analiz et.

GÜVENLİK VE GİZLİLİK KURALLARI (GUARDRAILS):
1. Belge geçerli bir finansal evrak (banka ekstresi, hesap dökümü, kredi kartı ekstresi, mobil bankacılık işlem listesi, dekont özeti, fatura, fiş, adisyon vb.) DEĞİLSE:
   {{"is_valid_document": false, "error": "Yüklenen belge geçerli bir banka ekstresi veya fiş değildir. Kimlik, ehliyet veya kart fotoğrafları güvenlik sebebiyle işlenemez."}} döndür.
2. IBAN, Kredi Kartı numarası veya müşteri telefon numaralarını asla 'description' veya 'merchant' içine açık yazma; maskele (örn: TR**1234).
3. HASSAS VERİ TESPİTİ VE KOORDİNATLARI (IBAN / KART NO):
   - Belgede açık bir IBAN (TR ile başlayan numara) veya tam kredi kartı numarası varsa:
     * 'has_sensitive_data': true yap.
     * 'sensitive_boxes': Belgede bu IBAN veya kart numaralarının bulunduğu alanların 0-1000 normalize koordinatlarındaki [ymin, xmin, ymax, xmax] listesi (örn: [[120, 50, 160, 600]]).
   - Belgede IBAN, kart numarası veya kişisel veri YOKSA (standart fiş, market alışverişi, restoran adisyonu vb.):
     * 'has_sensitive_data': false
     * 'sensitive_boxes': []
4. SANSÜRLÜ ALANLAR VE GÜVENLİK BANTLARI:
   - Görsel üzerinde siyah bant, 'SANSÜRLENDİ' veya 'PII' etiketi varsa, bu kullanıcının yerel gizlilik kalkanı tarafından sansürlenmiş hassas verisidir (IBAN, kart no vb.).
   - Bu sansürlü bantları kesinlikle bir hata veya geçersiz evrak olarak algılama; bu alanları yok sayarak belgedeki diğer işlem kalemlerini, mağaza adını, tarihi ve genel toplam tutarını eksiksiz analiz et.

TUTAR VE PARA BİRİMİ AYRIŞTIRMA KURALLARI (ÇOK KRİTİK):
- Belgedeki sayı ve tutar formatlarını kesinlikle doğru ayrıştır:
  * Türk Lirası formatında nokta binlik ayracı, virgül ise kuruş ayracıdır (örn: '1.450,50 TL' -> 1450.50).
  * Uluslararası veya dijital formatta virgül binlik, nokta kuruş ayracı olabilir (örn: '1,450.50' -> 1450.50).
  * Kuruşsuz tutarlar (örn: '450 TL' veya '450,00' veya '450.00' -> 450.00).
  * KESİNLİKLE ondalık haneyi silip tutarı 100 ile çarpma (Örn: 450.00 TL'yi sakın 45000 yapma, 14.50 TL'yi 1450 yapma!).
  * Tüm 'amount', 'total_expense' ve 'total_income' değerleri pozitif float (ondalıklı sayı) olmalıdır.

BELGE TÜRÜ AYRIMI:
A) BANKA VEYA KREDİ KARTI EKSTRESİ / HESAP DÖKÜMÜ:
   - Mobil bankacılık ekran görüntüsü, dekont listesi, e-ekstre, hesap özeti veya birden fazla işlem içeren finansal liste.
   - Ekrandaki veya belgedeki TÜM işlem satırlarını tek tek ayıkla.
   - Her işlem satırı için:
     * 'amount': Pozitif ondalıklı sayı (örn: 845.50).
     * 'type': Paranın akış yönü. Harcama, alışveriş, para transferi çıkışı, POS ödemesi veya borç için 'expense'; maaş, gelen transfer, iade veya para girişi için 'income'.
     * 'date': YYYY-MM-DD formatında işlem tarihi (yıl belirtilmemişse {current_year} yaz).
     * 'category': SADECE şu listeden seç: 'Market', 'Ulaşım', 'Teknoloji', 'Eğlence', 'Fatura', 'Kira', 'Sağlık', 'Eğitim', 'Giyim', 'Maaş', 'Yatırım', 'Diğer'.
     * 'description': İşlemin açıklaması/işyeri adı (örn: "Migros Sanal Market", "Shell Akaryakıt", "Ahmet Yılmaz Havale").
   - 'total_expense': Tüm 'expense' türündeki işlemlerin tutarlarının toplamı.
   - 'total_income': Tüm 'income' türündeki işlemlerin tutarlarının toplamı.
   - 'bank_name': Belgede veya mobil uygulamada adı geçen banka (Garanti BBVA, İş Bankası, Yapı Kredi, Akbank, Ziraat, Papara, QNB, Enpara vb.).

B) TEKİL PERAKENDE FİŞİ / ADİSYON / FATURA (GELİR VEYA GİDER):
   - Tek bir mağaza/market alışveriş fişi, restoran adisyonu veya tekil fatura (e-Arşiv Fatura, e-Fatura, Serbest Meslek Makbuzu vb.) ise `is_statement: false` yap.
   - FATURA / FİŞ GELİR Mİ GİDER Mİ TESPİTİ (EN KRİTİK ALAN):
     * 'transaction_type': Belge kullanıcı/işletme için bir GELİR ise 'income', bir GİDER/HARCAMA ise 'expense'.
     * 'document_kind': 
       - 'sales_invoice' (Kullanıcının müşterisine kestiği Satış Faturası / Hizmet Bedeli / Serbest Meslek Makbuzu)
       - 'expense_invoice' (Alış Faturası / Hizmet veya Mal Alım Faturası / Elektrik, Su, Doğalgaz, İnternet vb.)
       - 'retail_receipt' (Perakende Market, Restoran, Kafe, Benzinlik Fişi veya Adisyon)
     * TESPİT KURALLARI:
       1. GELİR ('income'):
          - Belgede "e-Arşiv Fatura", "e-Fatura", "Serbest Meslek Makbuzu", "Hizmet Faturası", "Satış Faturası" veya "Tahsilat" ibareleri varsa VE:
          - Faturanın tipi alanında 'SATIŞ', 'HİZMET', 'İHRACAT', 'KOMİSYON' yazıyorsa veya faturayı düzenleyen (Satıcı) taraf kullanıcı/işletme ise ve müşteriye fatura kesilmişse:
            -> 'transaction_type': 'income'
            -> 'document_kind': 'sales_invoice'
            -> 'merchant': Faturanın kesildiği MÜŞTERİ / ALICI firma ya da şahsın adı (örn: "ABC Bilişim Ltd. Şti. (Müşteri)").
            -> 'category': 'Satış Geliri', 'Hizmet / Danışmanlık', 'Hak Ediş', 'Maaş', 'Yatırım' veya 'Diğer' arasından en uygun olanı.
            -> 'description': Kısa fatura açıklaması (örn: "ABC Bilişim Satış Faturası").
       2. GİDER ('expense'):
          - Perakende market fişleri (Migros, BİM, A101, Şok vb.), restoran/kafe adisyonları, benzinlik fişleri -> 'transaction_type': 'expense', 'document_kind': 'retail_receipt'.
          - Kullanıcıya kesilmiş elektrik, su, internet, telefon faturaları (Türk Telekom, Enerjisa, İSKİ vb.) veya tedarikçilerden alınmış mal/hizmet alış faturaları -> 'transaction_type': 'expense', 'document_kind': 'expense_invoice'.
          - 'merchant': Fişi/faturayı kesen SATICI / MAĞAZA / İŞLETME adı (örn: "Migros", "Shell", "Enerjisa").
          - 'category': 'Market', 'Ulaşım', 'Malzeme / Stok', 'Ofis & Kira', 'Teknoloji', 'Fatura', 'Kargo & Lojistik', 'Reklam & Pazarlama', 'Sağlık', 'Eğitim', 'Giyim' veya 'Diğer'.
          - 'description': Kısa harcama açıklaması (örn: "Migros Market Alışverişi", "Ofis Elektrik Faturası").
   - 'amount': Fişin veya faturanın üzerindeki en alt nihai GENEL TOPLAM (ÖDENECEK TUTAR / KDV DAHİL ÖDENECEK NET TUTAR) değeridir.
     * UYARI: Ara toplamı (subtotal), KDV tutarını, para üstünü veya faturadaki tek bir kalemin fiyatını GENEL TOPLAM yerine alma! Faturanın en altındaki en büyük nihai ödenecek genel toplam tutarını al.
   - 'date': Belge üzerindeki düzenleme tarihi (YYYY-MM-DD, yoksa {today_str}).

ÇOKLU İŞLEM VEYA BANKA EKSTRESİ İSE DÖNDÜRECEĞİN JSON ŞEMASI:
{{
    "is_valid_document": true,
    "is_statement": true,
    "bank_name": "Garanti BBVA",
    "summary_text": "Ekstrenizde toplam X adet işlem tespit edildi.",
    "total_expense": 1450.50,
    "total_income": 0.00,
    "currency": "TRY",
    "has_sensitive_data": false,
    "sensitive_boxes": [],
    "transactions": [
        {{
            "date": "YYYY-MM-DD",
            "description": "Migros Sanal Market",
            "amount": 845.50,
            "type": "expense",
            "category": "Market"
        }}
    ]
}}

TEKİL FİŞ VEYA FATURA İSE DÖNDÜRECEĞİN JSON ŞEMASI:
{{
    "is_valid_document": true,
    "is_statement": false,
    "is_valid_receipt": true,
    "transaction_type": "income",
    "document_kind": "sales_invoice",
    "merchant": "Müşteri veya Satıcı Adı",
    "amount": 2450.00,
    "currency": "TRY",
    "date": "{today_str}",
    "category": "Satış Geliri",
    "description": "Müşteri Satış Faturası",
    "has_sensitive_data": false,
    "sensitive_boxes": []
}}

ÇOK ÖNEMLİ: Yanıtını SADECE ve MUTLAKA geçerli bir JSON bloğu olarak döndür! Markdown formatında veya ek metin olmadan saf JSON ver.
"""

    if not GEMINI_API_KEY:
        return {
            "is_valid_document": True,
            "is_statement": True,
            "bank_name": "Örnek Banka Ekstresi (Demo)",
            "summary_text": "Demo ekstreniz incelendi. 3 adet işlem tespit edildi.",
            "total_expense": 1850.0,
            "total_income": 0.0,
            "currency": "TRY",
            "transactions": [
                {"date": today_str, "description": "Migros Market", "amount": 450.0, "type": "expense", "category": "Market"},
                {"date": today_str, "description": "Shell Akaryakıt", "amount": 1200.0, "type": "expense", "category": "Ulaşım"},
                {"date": today_str, "description": "Netflix Aboneliği", "amount": 200.0, "type": "expense", "category": "Eğlence"}
            ]
        }

    candidate_models = ["gemini-3.6-flash", "gemini-3.5-flash"]

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inlineData": {
                            "mimeType": mime_type if mime_type.startswith("image/") or mime_type == "application/pdf" else "application/pdf",
                            "data": base64_data
                        }
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json"
        }
    }

    last_error = ""
    for model_name in candidate_models:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=35) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                if "candidates" in res_data and res_data["candidates"]:
                    candidate = res_data["candidates"][0]
                    raw_text = candidate["content"]["parts"][0]["text"].strip()
                    if raw_text.startswith("```json"):
                        raw_text = raw_text.split("```json")[1].split("```")[0].strip()
                    elif raw_text.startswith("```"):
                        raw_text = raw_text.split("```")[1].split("```")[0].strip()

                    parsed = json.loads(raw_text)
                    parsed["usage_metadata"] = res_data.get("usageMetadata", {})
                    parsed["model_used"] = model_name

                    # Sayı ve Tutar Temizleme Yardımcısı (Türkçe ve Uluslararası format desteği)
                    def clean_amount_value(val):
                        try:
                            if isinstance(val, (int, float)):
                                return abs(float(val))
                            s = str(val).replace("₺", "").replace("TL", "").replace("TRY", "").strip()
                            if not s:
                                return 0.0
                            # Eğer hem nokta hem virgül varsa (örn '1.450,50' veya '1,450.50')
                            if "," in s and "." in s:
                                if s.find(".") < s.find(","):
                                    # '1.450,50' -> nokta binlik, virgül ondalık
                                    s = s.replace(".", "").replace(",", ".")
                                else:
                                    # '1,450.50' -> virgül binlik, nokta ondalık
                                    s = s.replace(",", "")
                            elif "," in s:
                                # '450,50' -> '450.50'
                                s = s.replace(",", ".")
                            return abs(float(s))
                        except Exception:
                            return 0.0

                    # PII Maskeleme ve Tutar Doğrulama
                    if parsed.get("is_statement") and "transactions" in parsed and isinstance(parsed["transactions"], list):
                        computed_expense = 0.0
                        computed_income = 0.0
                        for tx in parsed["transactions"]:
                            amt_val = clean_amount_value(tx.get("amount", 0))
                            tx["amount"] = round(amt_val, 2)
                            tx_type = (tx.get("type") or "expense").lower()
                            if tx_type == "expense":
                                computed_expense += amt_val
                            else:
                                computed_income += amt_val
                            tx["description"] = AIGuardrails.mask_sensitive_data(tx.get("description", "İşlem"))

                        # LLM toplama hatalarını ezip kesin matematiksel toplamı yaz:
                        parsed["total_expense"] = round(computed_expense, 2)
                        parsed["total_income"] = round(computed_income, 2)

                    elif not parsed.get("is_statement"):
                        # Tekil fiş/fatura
                        raw_receipt_amt = clean_amount_value(parsed.get("amount", 0))
                        parsed["amount"] = round(raw_receipt_amt, 2)

                        # Gelir / Gider tipi sanitizasyonu
                        raw_type = str(parsed.get("transaction_type", "")).strip().lower()
                        if raw_type in ["income", "gelir"]:
                            parsed["transaction_type"] = "income"
                        else:
                            parsed["transaction_type"] = "expense"

                        if not parsed.get("document_kind"):
                            parsed["document_kind"] = "sales_invoice" if parsed["transaction_type"] == "income" else "retail_receipt"

                        if parsed.get("description"):
                            parsed["description"] = AIGuardrails.mask_sensitive_data(parsed["description"])
                        if parsed.get("merchant"):
                            parsed["merchant"] = AIGuardrails.mask_sensitive_data(parsed["merchant"])

                    # Hassas Veri Bayraklarını ve Koordinatlarını Normalize Et
                    parsed["has_sensitive_data"] = bool(parsed.get("has_sensitive_data", False))
                    parsed["sensitive_boxes"] = parsed.get("sensitive_boxes") if isinstance(parsed.get("sensitive_boxes"), list) else []

                    print(f"✅ [Statement Parse] {model_name} başarıyla ayrıştırdı: is_statement={parsed.get('is_statement')}, count={len(parsed.get('transactions', []))}, has_sensitive_data={parsed['has_sensitive_data']}")
                    return parsed
        except Exception as e:
            last_error = str(e)
            print(f"[Statement Parse Error] Model {model_name}: {e}")
            continue

    # Modeller yanıt veremediyse kullanıcıya net hata dön
    return {
        "is_valid_document": False,
        "error": f"Ekstre görseli/belgesi yapay zeka tarafından ayrıştırılamadı ({last_error or 'Servis yanıt vermedi'}). Lütfen görselin net olduğundan veya PDF/CSV formatında yüklediğinizden emin olun."
    }
