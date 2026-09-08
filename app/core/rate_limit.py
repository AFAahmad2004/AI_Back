import time
from collections import defaultdict, deque

import redis
from fastapi import Depends, HTTPException, status

from app.core.config import settings
from app.core.security import get_current_user
from app.models.user import User

# حد قابل للتعديل من .env — لا حدّ داخلي مفروض من التطبيق نفسه بشكل ثابت.
# ⚠️ ملاحظة مهمة يجب معرفتها: هذا الحد يحمي فقط من طلبات هذا التطبيق نفسه
# — Google لديها حصة يومية/دقائقية خاصة بها على مستوى مفتاح Gemini (خارج
# سيطرة هذا الكود تمامًا)، ورفع هذا الحد أو تعطيله لا "يُلغي" حدود Google
# الفعلية؛ فقط يمنع هذا التطبيق من حجب المستخدم قبل الوصول لحدود Google.
# القيمة الافتراضية عالية جدًا (فعليًا بلا حدّ عملي في الاستخدام الطبيعي).
_WINDOW_SECONDS = 3600  # ساعة واحدة
_MAX_REQUESTS_PER_WINDOW = settings.ai_rate_limit_per_hour

# --- تخزين احتياطي في الذاكرة (Fallback) ---
# يُستخدم فقط عند عدم تهيئة REDIS_URL، أو عند تعذّر الاتصال الفعلي بـ Redis
# (مثل بيئة تطوير محلية بسيطة بلا Redis مثبَّت). يعمل بشكل صحيح تمامًا
# طالما السيرفر نسخة واحدة فقط — لا يعمل بشكل صحيح عبر عدة نسخ (لهذا Redis
# هو الحل الموصى به فعليًا في الإنتاج).
_memory_log: dict[int, deque] = defaultdict(deque)


def _check_memory_fallback(user_id: int) -> bool:
    """يُعيد True إذا سُمح بالطلب، False إذا تجاوز الحد."""
    now = time.time()
    log = _memory_log[user_id]
    while log and now - log[0] > _WINDOW_SECONDS:
        log.popleft()
    if len(log) >= _MAX_REQUESTS_PER_WINDOW:
        return False
    log.append(now)
    return True


# --- عميل Redis (اختياري) ---
_redis_client: redis.Redis | None = None
_redis_unavailable_logged = False

if settings.redis_url:
    try:
        _redis_client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1)
        _redis_client.ping()  # تحقّق فوري أن الاتصال يعمل فعليًا، وليس افتراضًا فقط
    except Exception:
        # Redis مُهيَّأ في .env لكن غير قابل للوصول فعليًا (مطفأ، عنوان خاطئ...)
        # — نتراجع للذاكرة بدل فشل السيرفر بالكامل عند بدء التشغيل.
        _redis_client = None


def _check_redis(user_id: int) -> bool:
    """نافذة منزلقة بسيطة عبر INCR + EXPIRE — ذرّية وموزَّعة فعليًا عبر Redis،
    بعكس النسخة في الذاكرة."""
    key = f"ai_rate_limit:{user_id}"
    try:
        count = _redis_client.incr(key)
        if count == 1:
            _redis_client.expire(key, _WINDOW_SECONDS)
        return count <= _MAX_REQUESTS_PER_WINDOW
    except Exception:
        # فشل اتصال لحظي بـ Redis أثناء التشغيل الفعلي — نسمح بالطلب بدل
        # حجب المستخدم بسبب مشكلة بنية تحتية لا علاقة له بها، ونتراجع
        # للذاكرة لبقية هذا الطلب فقط.
        return _check_memory_fallback(user_id)


def rate_limit_ai(current_user: User = Depends(get_current_user)) -> User:
    allowed = (
        _check_redis(current_user.id)
        if _redis_client is not None
        else _check_memory_fallback(current_user.id)
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"تجاوزت الحد المسموح به لطلبات الذكاء الاصطناعي "
            f"({_MAX_REQUESTS_PER_WINDOW} طلبًا في الساعة). حاول لاحقًا.",
        )
    return current_user
