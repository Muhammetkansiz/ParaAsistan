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
    def inspect_input(cls, user_message: str) -> Tuple[bool, Optional[str], str]:
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

        # 3. Adım: Hassas Kişisel Verileri Maskele
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
