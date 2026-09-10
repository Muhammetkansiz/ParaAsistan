# backend/guardrails.py
# ParaAsistan - AI Güvenlik ve Kişisel Veri Koruma (Guardrails) Katmanı

import re
from typing import Tuple, Optional

class AIGuardrails:
    """
    Yapay zeka modelleri için 3 katmanlı güvenlik ve veri koruma kalkanı:
    1. PII (Hassas Kişisel Veri) Maskeleme (Kredi Kartı, IBAN, TCKN)
    2. Prompt Injection & Jailbreak Koruması
    3. Zararlı ve Yasadışı İçerik Filtresi
    """

    # 1. Zararlı / Yasadışı Anahtar Kelimeler
    DANGEROUS_KEYWORDS = [
        "bomba", "bomb", "silah", "patlayıcı", "uyuşturucu", 
        "suikast", "zehir", "nükleer", "kaçakçılık", "kara para"
    ]

    # 2. Prompt Injection & Rol Değiştirme Saldırı Kalıpları
    INJECTION_PATTERNS = [
        r"ignore (all )?previous instructions",
        r"önceki (tüm )?talimatları unut",
        r"tüm kuralları unut",
        r"sen artık bir",
        r"system prompt(unu)? göster",
        r"bütün kuralları sil",
        r"sen kimsin kuralların neler",
        r"jailbreak",
        r"dan moduna geç"
    ]

    # 3. Gizlilik ve Başka Kullanıcı / Hesap Sorguları
    PRIVACY_REPLY = (
        "Ben sizin kişisel finans danışmanınızım. Gizlilik ve güvenlik politikaları gereği "
        "yalnızca kendi hesabınıza ait verileri görüntüleyebilir ve yorumlayabilirim. "
        "Diğer kullanıcıların finansal bilgilerine erişimim bulunmamaktadır."
    )

    PRIVACY_PATTERNS = [
        r"\b(diğer|başka|farklı|öbür)\s+(kullanıcı|hesap|üye|insan|kişi|profil|müşteri)(lar|ler)?(in|ın|ün|un)?\b",
        r"\b(başkalarının|başkası|başkasının|diğerlerinin)\s+(veri|hesap|bakiye|harcama|para|bilgi|gelir|gider)(ler|leri)?\b",
        r"\b(tüm|bütün|herkesin)\s+(kullanıcı|hesap|üye)lar(ın)?\s+(veri|bakiye|harcama|para|bilgi|hesap)\b",
        r"\b(sistemdeki|veritabanındaki)\s+(kullanıcı|hesap|üye)(lar|ler)?\b",
        r"\b(benden|kendi\s+hesabımdan)\s+başka\b",
        r"\bbaşka\s+kullanıcı\b",
        r"\bdiğer\s+hesap\b",
        r"\bbaşkası(nın)?\s+hesab",
    ]

    @classmethod
    def detect_sensitive_data(cls, text: str) -> Optional[str]:
        """
        Metin içerisinde IBAN, Kredi Kartı, TCKN, Şifre/CVV gibi hassas veriler
        olup olmadığını denetler. Bulunursa türünü döner, yoksa None.
        """
        # A) IBAN (TR ile başlayan 26 karakter)
        if re.search(r'\bTR\d{2}[ ]?(?:\d{4}[ ]?){5}\d{2}\b', text, flags=re.IGNORECASE):
            return "IBAN Numarası"

        # B) Kredi / Banka Kartı (13-16 haneli ardışık sayılar)
        # Sadece cep telefonu veya tarih olmayan 13-16 haneli kart kalıbı
        card_match = re.search(r'\b(?:\d[ -]*?){13,16}\b', text)
        if card_match:
            digits_only = re.sub(r'\D', '', card_match.group(0))
            if len(digits_only) in (13, 14, 15, 16):
                # Telefon numarası (05xx veya 5xx) değilse
                if not (len(digits_only) == 11 and digits_only.startswith('05')) and not (len(digits_only) == 10 and digits_only.startswith('5')):
                    return "Kredi/Banka Kartı Numarası"

        # C) TC Kimlik Numarası (11 haneli ve 0 ile başlamayan)
        if re.search(r'\b[1-9]\d{10}\b', text):
            return "TC Kimlik Numarası"

        # D) CVV / Şifre / Parola / PIN
        if re.search(r'(?i)\b(şifrem|parolam|pinim|cvv)\s*[:=]?\s*(\w+)\b', text):
            return "Güvenlik Şifresi / PIN / CVV"

        return None

    @classmethod
    def mask_sensitive_data(cls, text: str) -> str:
        """
        Metin içerisindeki kredi kartı, IBAN ve TC Kimlik No gibi
        özel verileri yapay zekaya gitmeden önce maskeler (sansürler).
        """
        masked = text

        # A) Türkiye IBAN Numaraları (TR ile başlayan 26 karakter) - Önce IBAN maskelenir
        def mask_iban(m):
            clean = re.sub(r'\s+', '', m.group(0))
            return f"TR** **** **** **** **** {clean[-4:]}"

        masked = re.sub(r'\bTR\d{2}[ ]?(?:\d{4}[ ]?){5}\d{2}\b', mask_iban, masked, flags=re.IGNORECASE)

        # B) Kredi / Banka Kartı Numaraları (13-16 haneli, aralıklı veya bitişik)
        def mask_card(m):
            digits = re.sub(r'\D', '', m.group(0))
            last4 = digits[-4:]
            return f"****-****-****-{last4}"

        masked = re.sub(r'\b(?:\d[ -]*?){13,16}\b', mask_card, masked)

        # C) TC Kimlik Numarası (11 haneli, 0 ile başlamayan sayılar)
        masked = re.sub(r'\b[1-9]\d{10}\b', '***********', masked)

        # D) Türkiye Cep Telefonu Numaraları (05xx xxx xx xx)
        masked = re.sub(r'(?:\+?90\s*|0)?(5\d{2})[\s.-]?(\d{3})[\s.-]?(\d{2})[\s.-]?(\d{2})\b', r'0\1 *** ** \4', masked)

        # E) Basit Parola / PIN Kalıpları
        masked = re.sub(r'(?i)\b(şifrem|parolam|pinim|cvv)\s*[:=]?\s*(\w+)\b', r'\1: [GİZLENDİ]', masked)

        return masked

    @classmethod
    def check_privacy_violation(cls, user_message: str, current_user_name: Optional[str] = None) -> bool:
        """
        Kullanıcının başka bir kişinin, hesabın veya sistemdeki genel kullanıcıların
        verilerini sorgulayıp sorgulamadığını denetler.
        """
        lower_msg = user_message.lower().strip()

        # Genel başka hesap / diğer kullanıcı kalıpları
        for p in cls.PRIVACY_PATTERNS:
            if re.search(p, lower_msg, flags=re.IGNORECASE):
                return True

        current_first_name = (current_user_name or "").strip().split()[0].lower() if current_user_name else ""
        ignored_words = {
            "ben", "benim", "biz", "bizim", "kendi", "hesap", "bütçe", "şirket", "ev", "aile",
            "bugün", "dün", "bu ay", "geçen ay", "toplam", "şu an", "kullanıcı", "para", "market"
        }

        # İsimle sorgulama kalıbı (Örn: "Ahmet'in bakiyesi", "Ayşe'nin harcamaları")
        name_match = re.search(r"\b([a-zçğıöşü]{3,})('in|'ın|'ün|'un|'nin|'nın|'nün|'nun|in|ın|ün|un)\s+(hesap|bakiye|harcama|para|gider|gelir|bütçe|durum)", lower_msg)
        if name_match:
            queried_name = name_match.group(1).lower()
            if queried_name not in ignored_words and (not current_first_name or queried_name != current_first_name):
                return True

        # "Ahmet ne kadar harcamış / parası ne kadar" kalıbı
        spent_match = re.search(r"\b([a-zçğıöşü]{3,})\s+(ne kadar|kaç para|kaç tl)\s+(harcadı|harcamış|kazandı|kazanmış|var|bakiye)", lower_msg)
        if spent_match:
            queried_name = spent_match.group(1).lower()
            if queried_name not in ignored_words and (not current_first_name or queried_name != current_first_name):
                return True

        return False

    @classmethod
    def inspect_input(cls, user_message: str, current_user_name: Optional[str] = None) -> Tuple[bool, Optional[str], str]:
        """
        Kullanıcı girdisini denetler:
        Döner: (is_safe: bool, block_reason: str, sanitized_message: str)
        """
        lower_msg = user_message.lower().strip()

        # 1. Adım: Zararlı / Yasadışı kelime denetimi
        if any(k in lower_msg for k in cls.DANGEROUS_KEYWORDS):
            return (
                False,
                "Tehlikeli, yasadışı veya zararlı içeriklerle ilgili değerlendirme yapamam. Yalnızca yasal kişisel harcamalarınız ve bütçe planlamanız konusunda yardımcı olabilirim.",
                user_message
            )

        # 2. Adım: Prompt Injection denetimi
        for pattern in cls.INJECTION_PATTERNS:
            if re.search(pattern, lower_msg):
                return (
                    False,
                    "Güvenlik Uyarısı: Sistem talimatlarını ve rolünü değiştirme girişimleri güvenlik politikası gereği işlenemez. Kişisel bütçenizle ilgili nasıl yardımcı olabilirim?",
                    user_message
                )

        # 3. Adım: Gizlilik & Başka Kullanıcı / Hesap Sorgusu Denetimi
        if cls.check_privacy_violation(user_message, current_user_name):
            return (
                False,
                cls.PRIVACY_REPLY,
                user_message
            )

        # 4. Adım: Hassas Kişisel Veri Denetimi (Yapay Zekaya Asla Gönderilmez, Kapıda Engellenir)
        sensitive_found = cls.detect_sensitive_data(user_message)
        if sensitive_found:
            return (
                False,
                f"Güvenlik ve Gizlilik Uyarısı: Mesajınızda '{sensitive_found}' tespit edildi. Kişisel veri güvenliğiniz gereği bu bilgiler yapay zekaya kesinlikle gönderilmez ve işlenemez. Lütfen kart, IBAN veya kimlik bilgisi paylaşmadan sorunuzu tekrar iletiniz.",
                user_message
            )

        # 5. Adım: Ekstra PII Temizliği (Her ihtimale karşı arta kalan kalıpları maskele)
        sanitized = cls.mask_sensitive_data(user_message)

        return (True, None, sanitized)

    @classmethod
    def inspect_output(cls, ai_reply: str) -> str:
        """
        Modelin ürettiği yanıtı denetler:
        Yatırım tavsiyesi (SPK) riski varsa yasal uyarı notu ekler.
        """
        lower_reply = ai_reply.lower()
        investment_triggers = ["hisse", "kripto", "bitcoin", "borsa", "altın al", "döviz al"]

        if any(t in lower_reply for t in investment_triggers):
            if "yatırım tavsiyesi" not in lower_reply:
                ai_reply += "\n\n*(Not: Bu değerlendirme kişisel harcama tavsiyesi olup SPK kapsamında yatırım tavsiyesi niteliği taşımamaktadır.)*"

        return ai_reply
