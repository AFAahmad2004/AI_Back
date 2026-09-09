import logging

from google import genai
from google.genai import types
from google.genai.errors import APIError

from app.core.config import settings

logger = logging.getLogger("ai_service")

# gemini-3.6-flash: نموذج المحادثة السريع ضمن الطبقة المجانية من Gemini.
# ⚠️ ملاحظة تحديث: كان الكود يستخدم "gemini-2.0-flash"، لكن Google أوقفت
# دعمه رسميًا (رسالة الخطأ 404 التي تُعيدها الآن تقول بالحرف: "This model
# models/gemini-2.0-flash is no longer available... use models/gemini-3.6-flash").
# اكتُشف هذا فعليًا عبر diagnose_gemini.py وليس افتراضًا نظريًا.
# text-embedding-004: نموذج Embeddings المجاني من نفس المزوّد.
# راجع §26 من المواصفات: النظام مصمَّم أصلًا ليكون غير مرتبط بمزوّد واحد —
# هذا هو الملف الوحيد الذي يعرف اسم المزوّد الفعلي (Gemini)؛ أي مكان آخر
# في المشروع (retrieval.py, quiz_generation.py, flashcard_generation.py,
# الـ routers) يستدعي فقط embed_text()/chat_completion() دون أي تغيير.
CHAT_MODEL = "gemini-3.6-flash"
EMBEDDING_MODEL = "text-embedding-004"


class AIServiceUnavailable(Exception):
    """يُرفع عندما لا يوجد GEMINI_API_KEY مُعرَّف على الإطلاق (§30: المفاتيح
    من Backend فقط، ولا تصل أبدًا لتطبيق Flutter)."""


class AIServiceError(Exception):
    """يُرفع عند فشل فعلي في الاتصال بمزوّد الذكاء الاصطناعي (شبكة، مفتاح
    خاطئ، حصة يومية منتهية، حظر محتوى...) — أي خطأ غير متوقّع من الشبكة
    أو المزوّد، حتى لو لم يكن من النوع الذي توقّعناه بالضبط."""


def _client() -> genai.Client:
    if not settings.gemini_api_key:
        raise AIServiceUnavailable(
            "ميزات الذكاء الاصطناعي غير مفعّلة على الخادم. "
            "أضف GEMINI_API_KEY في ملف .env لتفعيلها (مجاني عبر aistudio.google.com)."
        )
    return genai.Client(api_key=settings.gemini_api_key)


def embed_text(text: str) -> list[float]:
    client = _client()
    try:
        response = client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text[:8000],
            config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
        )
        return list(response.embeddings[0].values)
    except AIServiceUnavailable:
        raise
    except (APIError, Exception) as e:
        # نلتقط كل شيء بأمان (وليس فقط APIError الموثّقة) لأن مكتبات AI
        # الخارجية قد ترفع أنواع أخطاء متنوعة (شبكة، تحليل استجابة، حظر
        # محتوى) لا يمكن حصرها جميعًا مسبقًا — الأهم ألا يصل أي منها
        # كاستثناء غير مُعالَج إلى المستخدم.
        # ⚠️ نُسجّل الخطأ الحقيقي الكامل (بما في ذلك Traceback) في لوغ
        # الخادم قبل تحويله لرسالة عامة للمستخدم — بدون هذا، حتى لوغ
        # Render نفسه لا يُظهر السبب الفعلي (اكتُشف هذا فعليًا من مستخدم
        # حقيقي واجه رسالة عامة بلا أي تفاصيل قابلة للتشخيص في أي مكان).
        logger.exception(f"فشل استدعاء Gemini الفعلي: {type(e).__name__}: {e}")
        raise AIServiceError("تعذّر الاتصال بخدمة الذكاء الاصطناعي حاليًا.") from e


def read_text_from_image_bytes(image_bytes: bytes, prompt: str, mime_type: str = "image/png") -> str:
    """يستخدم قدرة Gemini الأصلية على قراءة الصور (Multimodal) — بديل عن
    OCR تقليدي (Tesseract) لا يحتاج أي برنامج نظام خارجي، ويعمل على أي
    بيئة استضافة قياسية (مثل Render) دون إعداد إضافي. راجع §7 و
    app/services/text_extraction.py."""
    client = _client()
    try:
        response = client.models.generate_content(
            model=CHAT_MODEL,
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                        types.Part(text=prompt),
                    ],
                )
            ],
            config=types.GenerateContentConfig(temperature=0.0),
        )
        return response.text or ""
    except AIServiceUnavailable:
        raise
    except (APIError, Exception) as e:
        logger.exception(f"فشل استدعاء Gemini الفعلي: {type(e).__name__}: {e}")
        raise AIServiceError("تعذّر الاتصال بخدمة الذكاء الاصطناعي حاليًا.") from e


def chat_completion_stream(
    system_prompt: str,
    user_prompt: str,
    history: list[dict] | None = None,
):
    """
    نسخة بثّية (Streaming) من chat_completion — تُعيد Generator يُصدر
    أجزاء النص فور توليدها من Gemini، بدل انتظار الرد الكامل. هذا يُحسّن
    الإحساس بالسرعة بشكل كبير في المحادثة (يظهر النص تدريجيًا كلمة بكلمة
    مثل ChatGPT) بدل شاشة انتظار ثم ظهور كل شيء دفعة واحدة.
    نفس منطق بناء السياق (history) والأدوار بالضبط كـ chat_completion.
    """
    client = _client()
    try:
        contents: list[types.Content] = []
        for msg in (history or []):
            role = "model" if msg["role"] == "assistant" else "user"
            contents.append(types.Content(role=role, parts=[types.Part(text=msg["content"])]))
        contents.append(types.Content(role="user", parts=[types.Part(text=user_prompt)]))

        stream = client.models.generate_content_stream(
            model=CHAT_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.3,
            ),
        )
        for chunk in stream:
            if chunk.text:
                yield chunk.text
    except AIServiceUnavailable:
        raise
    except (APIError, Exception) as e:
        logger.exception(f"فشل استدعاء Gemini الفعلي: {type(e).__name__}: {e}")
        raise AIServiceError("تعذّر الاتصال بخدمة الذكاء الاصطناعي حاليًا.") from e


def chat_completion(
    system_prompt: str,
    user_prompt: str,
    history: list[dict] | None = None,
) -> str:
    """
    [history] اختياري: قائمة رسائل سابقة بالشكل [{"role": "user"|"assistant",
    "content": "..."}, ...]، بأقدمها أولًا. عند تمريرها، يُرسَل السؤال
    الجديد مع سياق المحادثة السابقة فعليًا للنموذج (§10: "تذكّر" الأسئلة
    السابقة داخل نفس المحادثة)، بدل معاملة كل سؤال كمحادثة منفصلة تمامًا.
    Gemini يستخدم "model" وليس "assistant" كاسم للدور — التحويل يتم هنا
    فقط، بحيث تبقى بقية النظام (قاعدة البيانات، الـ routers) بلا معرفة
    بتفاصيل تسمية المزوّد الفعلي (§26).
    """
    client = _client()
    try:
        contents: list[types.Content] = []
        for msg in (history or []):
            role = "model" if msg["role"] == "assistant" else "user"
            contents.append(types.Content(role=role, parts=[types.Part(text=msg["content"])]))
        contents.append(types.Content(role="user", parts=[types.Part(text=user_prompt)]))

        response = client.models.generate_content(
            model=CHAT_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.3,
            ),
        )
        return response.text or ""
    except AIServiceUnavailable:
        raise
    except (APIError, Exception) as e:
        logger.exception(f"فشل استدعاء Gemini الفعلي: {type(e).__name__}: {e}")
        raise AIServiceError("تعذّر الاتصال بخدمة الذكاء الاصطناعي حاليًا.") from e
