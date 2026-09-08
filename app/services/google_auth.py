from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

from app.core.config import settings


class GoogleAuthUnavailable(Exception):
    """يُرفع عندما لا يوجد GOOGLE_CLIENT_ID مُعرَّف على الإطلاق."""


class GoogleTokenInvalid(Exception):
    """يُرفع عندما يفشل التحقق من صحة ID Token (منتهي، موقَّع لتطبيق آخر،
    أو مزيَّف بالكامل)."""


def verify_google_id_token(token: str) -> dict:
    """
    يتحقق من صحة ID Token فعليًا مع خوادم Google (وليس مجرد فك تشفيره محليًا
    بدون تحقق من التوقيع). يُعيد قاموسًا يحوي على الأقل: email, name, sub
    (مُعرِّف حساب Google الفريد).
    """
    if not settings.google_client_id:
        raise GoogleAuthUnavailable(
            "تسجيل الدخول عبر Google غير مفعَّل على الخادم. "
            "أضف GOOGLE_CLIENT_ID في ملف .env لتفعيله."
        )
    try:
        payload = google_id_token.verify_oauth2_token(
            token, google_requests.Request(), audience=settings.google_client_id
        )
    except ValueError as e:
        # يشمل: توقيع غير صالح، رمز منتهي الصلاحية، أو audience غير مطابق.
        raise GoogleTokenInvalid("رمز Google غير صالح أو منتهي الصلاحية.") from e

    if not payload.get("email"):
        raise GoogleTokenInvalid("لم يتضمّن حساب Google بريدًا إلكترونيًا صالحًا.")

    return payload
