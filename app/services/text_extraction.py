import logging

from pypdf import PdfReader
from pypdf.errors import PdfReadError

logger = logging.getLogger(__name__)

# حد أقصى لعدد الصفحات التي تخضع لـ OCR في ملف واحد — OCR بطيء نسبيًا
# (يُصيّر كل صفحة كصورة أولًا)، وهذا يحمي من تعليق الطلب طويلاً على ملف
# ضخم بالكامل ممسوح ضوئيًا. الصفحات الزائدة تبقى بلا نص (بدل تعليق الطلب).
MAX_OCR_PAGES = 30


def _ocr_page(file_path: str, page_number: int) -> str:
    """يُصيّر صفحة PDF واحدة كصورة، ثم يستخرج نصها عبر Tesseract OCR
    (عربي + إنجليزي معًا). يُستخدم فقط عندما يفشل الاستخراج النصي المباشر
    (§7: "إذا كان PDF عبارة عن صور Scanned، يجب استخدام OCR")."""
    try:
        from pdf2image import convert_from_path
        import pytesseract
    except ImportError:
        logger.warning("pytesseract/pdf2image غير مثبَّتَين — تخطّي OCR لهذه الصفحة.")
        return ""

    try:
        images = convert_from_path(file_path, first_page=page_number, last_page=page_number, dpi=200)
        if not images:
            return ""
        return pytesseract.image_to_string(images[0], lang="ara+eng").strip()
    except Exception as e:
        # فشل OCR (Tesseract غير مثبَّت على النظام، أو poppler مفقود...)
        # لا يجب أن يُسقط رفع الملف بالكامل — فقط تبقى هذه الصفحة بلا نص.
        logger.warning(f"فشل OCR للصفحة {page_number}: {e}")
        return ""


def extract_pdf_pages(file_path: str) -> list[dict]:
    """
    يستخرج النص الكامل من كل صفحة PDF. يُعيد قائمة
    [{"page_number": 1, "text": "...", "used_ocr": False}, ...].

    الخط الكامل (§7): يُحاول أولًا الاستخراج النصي المباشر (سريع، لملفات
    PDF نصّية فعلية). إذا كانت الصفحة فارغة النص (على الأرجح ممسوحة
    ضوئيًا/Scanned)، يتراجع تلقائيًا لـ OCR عبر Tesseract على تلك الصفحة
    تحديدًا — بحيث تُعالَج ملفات الصور والملفات النصية بنفس المسار دون أي
    فرق من ناحية المستخدم.
    """
    try:
        reader = PdfReader(file_path)
    except PdfReadError:
        return []

    pages = []
    ocr_used_count = 0
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = (page.extract_text() or "").strip()
        except Exception:
            text = ""

        used_ocr = False
        if not text and ocr_used_count < MAX_OCR_PAGES:
            text = _ocr_page(file_path, i)
            if text:
                used_ocr = True
                ocr_used_count += 1

        pages.append({"page_number": i, "text": text, "used_ocr": used_ocr})
    return pages
