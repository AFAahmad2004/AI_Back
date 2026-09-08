from pypdf import PdfReader
from pypdf.errors import PdfReadError


def count_pdf_pages(file_path: str) -> int:
    """
    يُعيد عدد صفحات ملف PDF. هذا أول لبنة فعلية من خط معالجة §7:

        Upload → Extract Text → (OCR إن لزم) → AI Processing → Save Results

    الخطوات التالية (خارج نطاق هذه المرحلة MVP) تشمل: استخراج النص الكامل
    لكل صفحة، تمييز PDF الممسوح ضوئيًا وتمريره عبر OCR، ثم تقسيم النص إلى
    Chunks وتوليد Embeddings لتغذية Vector Database (راجع §25).
    """
    try:
        reader = PdfReader(file_path)
        return len(reader.pages)
    except PdfReadError:
        # ملف تالف أو ليس PDF فعليًا — تُترجم لاحقًا لخطأ "Unsupported format" في الواجهة.
        return 0
