import logging

from pypdf import PdfReader
from pypdf.errors import PdfReadError

logger = logging.getLogger(__name__)

# حد أقصى لعدد الصفحات التي تخضع لقراءة صور — كل صفحة تستهلك استدعاء
# Gemini واحدًا، وهذا يحمي من تعليق رفع ملف ضخم بالكامل ممسوح ضوئيًا طويلًا،
# ومن استهلاك حصة Gemini المجانية دفعة واحدة على ملف واحد.
MAX_VISION_PAGES = 15

_VISION_PROMPT = (
    "انسخ كل النص الموجود في هذه الصورة بالضبط كما هو مكتوب، دون أي "
    "تعليق أو مقدّمة أو شرح إضافي منك. إذا لم يوجد أي نص واضح في الصورة، "
    "أعد سلسلة نصية فارغة فقط."
)


def _render_page_to_png(file_path: str, page_number: int) -> bytes | None:
    """يُصيّر صفحة PDF واحدة (فهرسها يبدأ من 1) كصورة PNG، باستخدام PyMuPDF
    — مكتبة بايثون خالصة (Wheel ذاتي الاكتفاء) لا تحتاج أي برنامج نظام
    خارجي مثل poppler، خلافًا لمكتبات أخرى شائعة. هذا مهم تحديدًا لأن
    الخادم عند نشره (مثل Render) لا يسمح بتثبيت برامج نظام إضافية بسهولة."""
    try:
        import pymupdf
    except ImportError:
        logger.warning("PyMuPDF غير مثبَّت — تخطّي معالجة الصورة لهذه الصفحة.")
        return None

    try:
        doc = pymupdf.open(file_path)
        try:
            page = doc.load_page(page_number - 1)  # PyMuPDF يبدأ الفهرسة من 0
            pixmap = page.get_pixmap(dpi=200)
            return pixmap.tobytes("png")
        finally:
            doc.close()
    except Exception as e:
        logger.warning(f"فشل تصيير الصفحة {page_number} كصورة: {e}")
        return None


def _read_text_from_image(image_bytes: bytes, mime_type: str = "image/png") -> str:
    """يستخدم قدرة Gemini الأصلية على قراءة الصور (Multimodal) لاستخراج
    النص منها — بديل عن Tesseract OCR التقليدي (§7). ميزتان مهمتان:
    1) لا يحتاج أي برنامج نظام خارجي (خلافًا لـ Tesseract الذي يحتاج
       تثبيتًا نظاميًا غير متاح على منصات استضافة مثل Render).
    2) جودة قراءة أعلى عمليًا من Tesseract التقليدي، خصوصًا لخطوط اليد
       أو جودة مسح ضوئي متوسطة."""
    from app.services.ai_service import (
        AIServiceUnavailable,
        AIServiceError,
        read_text_from_image_bytes,
    )

    try:
        return read_text_from_image_bytes(image_bytes, _VISION_PROMPT, mime_type=mime_type).strip()
    except (AIServiceUnavailable, AIServiceError) as e:
        # بلا مفتاح Gemini، أو فشل اتصال — تبقى هذه الصفحة بلا نص، دون
        # إسقاط رفع الملف بالكامل (نفس فلسفة معالجة الأخطاء في كل المشروع).
        logger.warning(f"تعذّرت قراءة الصورة عبر Gemini: {e}")
        return ""


def extract_image_page(file_path: str) -> list[dict]:
    """
    مخصَّص للملفات المرفوعة كصورة مباشرة (JPG/PNG، وليست مضمَّنة داخل PDF).
    §7/§6: "تصوير المحاضرة بالكاميرا" يرفع صورة مباشرة، وليس PDF — يجب أن
    يُعالَج هذا المسار بشكل مستقل عن extract_pdf_pages تمامًا (كان مفقودًا
    بالكامل سابقًا: `pypdf` لا يستطيع فتح ملف JPG أصلًا فيفشل بصمت، وتبقى
    الصورة المرفوعة بلا أي نص مستخرَج مهما كانت واضحة).
    """
    try:
        with open(file_path, "rb") as f:
            image_bytes = f.read()
    except OSError:
        return [{"page_number": 1, "text": "", "used_vision": False}]

    mime_type = "image/png" if file_path.lower().endswith(".png") else "image/jpeg"
    text = _read_text_from_image(image_bytes, mime_type=mime_type)
    return [{"page_number": 1, "text": text, "used_vision": bool(text)}]


def extract_pdf_pages(file_path: str) -> list[dict]:
    """
    يستخرج النص الكامل من كل صفحة PDF. يُعيد قائمة
    [{"page_number": 1, "text": "...", "used_vision": False}, ...].

    الخط الكامل (§7): يُحاول أولًا الاستخراج النصي المباشر (سريع، لملفات
    PDF نصّية فعلية، ومجاني بالكامل). إذا كانت الصفحة فارغة النص (على
    الأرجح ممسوحة ضوئيًا/صورة)، يتراجع تلقائيًا لقراءتها كصورة عبر Gemini
    (Vision) — بحيث تُعالَج ملفات الصور والملفات النصية بنفس المسار دون
    أي فرق من ناحية المستخدم، وبلا أي اعتماد على برامج نظام خارجية.
    """
    try:
        reader = PdfReader(file_path)
    except PdfReadError:
        return []

    pages = []
    vision_used_count = 0
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = (page.extract_text() or "").strip()
        except Exception:
            text = ""

        used_vision = False
        if not text and vision_used_count < MAX_VISION_PAGES:
            image_bytes = _render_page_to_png(file_path, i)
            if image_bytes:
                text = _read_text_from_image(image_bytes)
                if text:
                    used_vision = True
                    vision_used_count += 1

        pages.append({"page_number": i, "text": text, "used_vision": used_vision})
    return pages
