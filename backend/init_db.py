# backend/init_db.py
# ParaAsistan - Veritabanı Başlatma, Migration ve Varsayılan Veri Kurulum Modülü

from sqlalchemy import text
from database import engine, Base, SessionLocal
import models

def create_tables():
    """Tüm SQLAlchemy tablolarını veritabanında oluşturur (yoksa)."""
    Base.metadata.create_all(bind=engine)
    print("✅ Veritabanı tabloları hazır.")

def migrate_db_columns():
    """Gereken eksik kolonları ve admin yetkilerini veritabanında eşitler."""
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS currency VARCHAR DEFAULT 'TRY';"))
            conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS original_amount FLOAT;"))
            conn.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS exchange_rate FLOAT DEFAULT 1.0;"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE;"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;"))
            # Eski atıl chat_messages tablosunu temizle
            try:
                conn.execute(text("DROP TABLE IF EXISTS chat_messages CASCADE;"))
            except Exception:
                pass
            # İlk kayıtlı kullanıcıyı otomatik admin yapalım
            conn.execute(text("UPDATE users SET is_admin = TRUE WHERE id = (SELECT min(id) FROM users);"))
        print("✅ Veritabanı kolonları ve admin yetkisi başarıyla eşitlendi.")
    except Exception as e:
        print("⚠️ Migration uyarısı:", e)

def seed_default_categories():
    """Yeni açılan veya mevcut veritabanındaki eksik varsayılan kategorileri tamamlar."""
    db = SessionLocal()
    try:
        all_defaults = [
            # Gider Kategorileri
            models.Category(name="Market", type="expense", icon="shopping_cart", color="#e11d48"),
            models.Category(name="Kira", type="expense", icon="home", color="#2563eb"),
            models.Category(name="Fatura", type="expense", icon="bolt", color="#d97706"),
            models.Category(name="Ulaşım", type="expense", icon="directions_car", color="#059669"),
            models.Category(name="Teknoloji", type="expense", icon="laptop", color="#7c3aed"),
            models.Category(name="Eğlence", type="expense", icon="movie", color="#db2777"),
            models.Category(name="Sağlık", type="expense", icon="medical_services", color="#dc2626"),
            models.Category(name="Eğitim", type="expense", icon="school", color="#4f46e5"),
            models.Category(name="Abonelik", type="expense", icon="subscriptions", color="#8b5cf6"),
            models.Category(name="Aidat", type="expense", icon="apartment", color="#0284c7"),
            models.Category(name="Kredi / Borç", type="expense", icon="credit_card", color="#e11d48"),
            models.Category(name="Sigorta / Kasko", type="expense", icon="shield", color="#0d9488"),
            models.Category(name="Diğer", type="expense", icon="receipt", color="#64748b"),
            # Gelir Kategorileri
            models.Category(name="Maaş", type="income", icon="payments", color="#16a34a"),
            models.Category(name="Kira Geliri", type="income", icon="real_estate_agent", color="#0d9488"),
            models.Category(name="Freelance / Ek Gelir", type="income", icon="laptop_mac", color="#0284c7"),
            models.Category(name="Yatırım / Temettü", type="income", icon="trending_up", color="#2563eb"),
            models.Category(name="Burs / Harçlık", type="income", icon="school", color="#9333ea"),
            models.Category(name="Emekli Maaşı", type="income", icon="elderly", color="#059669"),
            models.Category(name="Satış Geliri", type="income", icon="storefront", color="#d97706"),
            models.Category(name="Diğer Gelir", type="income", icon="savings", color="#64748b"),
        ]

        existing_names = {c.name.lower() for c in db.query(models.Category).all()}
        new_cats = [cat for cat in all_defaults if cat.name.lower() not in existing_names]

        if new_cats:
            db.add_all(new_cats)
            db.commit()
            print(f"✅ {len(new_cats)} adet yeni kategori başarıyla veritabanına eklendi.")
    except Exception as e:
        db.rollback()
        print("⚠️ Kategoriler başlatılırken uyarı:", e)
    finally:
        db.close()

def init_db():
    """Veritabanını baştan sona başlatan ana fonksiyon."""
    print("🚀 Veritabanı kurulumu başlatılıyor...")
    create_tables()
    migrate_db_columns()
    seed_default_categories()
    print("🎉 Veritabanı başarıyla hazırlandı!")

if __name__ == "__main__":
    init_db()
