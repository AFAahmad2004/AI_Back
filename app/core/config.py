from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """
    كل الإعدادات الحساسة تأتي من متغيرات بيئة (Environment Variables) ولا
    تُكتب داخل الكود مباشرة — تماشيًا مع قسم الأمان §30 من المواصفات:
    "لا يتم وضع API Keys داخل تطبيق Flutter... كل المفاتيح تكون في Backend".
    """

    # في التطوير: SQLite محلي. في الإنتاج: بدّل القيمة إلى رابط PostgreSQL
    # مثل: postgresql+psycopg2://user:password@host:5432/ai_study_db
    database_url: str = Field(default="sqlite:///./ai_study.db")

    secret_key: str = Field(default="CHANGE_ME_IN_PRODUCTION_ENV_VARIABLE")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # يوم واحد لتسهيل التطوير

    upload_dir: str = "uploads"
    max_upload_size_mb: int = 50

    # مفتاح Gemini (مجاني — عبر aistudio.google.com) — يُقرأ من البيئة فقط،
    # ولا يصل أبدًا إلى تطبيق Flutter (§30). النظام مصمَّم ليكون غير مرتبط
    # بمزوّد واحد (§26)؛ لتبديله لاحقًا لمزوّد آخر، عدّل app/services/ai_service.py فقط.
    gemini_api_key: str | None = None

    # Redis لـ Rate Limiting المشترك عبر عدة نسخ من السيرفر (§30). اتركه
    # فارغًا للتطوير المحلي البسيط — يتراجع النظام تلقائيًا لحدّ في ذاكرة
    # العملية نفسها (كافٍ لسيرفر واحد فقط، راجع app/core/rate_limit.py).
    redis_url: str | None = None

    # مُعرِّف عميل OAuth من Google Cloud Console (Web Client ID) — مطلوب
    # للتحقق من صحة ID Token القادم من "المتابعة عبر Google" في Flutter
    # (§4). يُنشأ من https://console.cloud.google.com/apis/credentials،
    # وهو مختلف تمامًا عن GEMINI_API_KEY. بدونه، /api/auth/google يرفض كل
    # الطلبات بوضوح بدل قبول أي رمز مزيَّف.
    google_client_id: str | None = None

    # حد طلبات AI لكل مستخدم في الساعة (§30) — راجع core/rate_limit.py
    # للتفاصيل الكاملة عن سبب وجوده وحدوده الفعلية. القيمة الافتراضية
    # عالية جدًا عمدًا (بناءً على طلب صريح بعدم فرض حدّ عملي على الاستخدام
    # الطبيعي)؛ اخفضها في .env إذا احتجت حماية فعلية لاحقًا من الاستخدام
    # المفرط (مثل إساءة استخدام أو هجوم آلي).
    ai_rate_limit_per_hour: int = 10000

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
