"""
اختبار مركّز لخط معالجة "قراءة الصور عبر Gemini" (البديل الجديد عن
Tesseract) — يُزيّف عميل Gemini بالكامل، ويتحقق أن:
1) PyMuPDF يُصيّر صفحة PDF فعليًا كصورة PNG صالحة.
2) الصورة المُصيَّرة + الـ prompt الصحيح يصلان فعليًا لواجهة Gemini
   بالشكل الصحيح (Part.from_bytes بترميز الصورة الصحيح).
3) عند نجاح "الاستدعاء" المزيَّف، النص يُحفَظ في قاعدة البيانات كمقطع فعلي.
"""
import io
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(__file__))

DB_PATH = "test_vision.db"
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
os.environ["DATABASE_URL"] = f"sqlite:///./{DB_PATH}"
os.environ["GEMINI_API_KEY"] = "fake-key-for-mocked-test"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.core.config import settings  # noqa: E402

settings.gemini_api_key = "fake-key-for-mocked-test"

client = TestClient(app)
failures = []


def check(label, condition, extra=""):
    status = "OK " if condition else "FAIL"
    print(f"[{status}] {label} {extra}")
    if not condition:
        failures.append(label)


r = client.post(
    "/api/auth/register",
    json={"name": "Vision Test", "email": "visiontest@example.com", "password": "secret123"},
)
token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# إنشاء PDF حقيقي بلا طبقة نص (صورة فقط) لاختبار المسار الكامل فعليًا.
from PIL import Image, ImageDraw
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

img = Image.new("RGB", (600, 200), color="white")
draw = ImageDraw.Draw(img)
draw.rectangle([10, 10, 590, 190], outline="black")  # بلا نص فعلي — لسنا بحاجة قراءة حقيقية، فقط اختبار المسار
img.save("/tmp/_vision_test_img.png")

pdf_buf = io.BytesIO()
c = canvas.Canvas(pdf_buf, pagesize=letter)
c.drawImage("/tmp/_vision_test_img.png", 50, 500, width=300, height=100)
c.showPage()
c.save()
pdf_buf.seek(0)

captured_calls = []


def fake_generate_content(*, model, contents, config):
    captured_calls.append({"contents": contents, "config": config})
    fake_response = MagicMock()
    fake_response.text = "Mocked extracted text from image"
    return fake_response


with patch("app.services.ai_service.genai.Client") as MockClient:
    mock_instance = MagicMock()
    mock_instance.models.generate_content.side_effect = fake_generate_content
    MockClient.return_value = mock_instance

    r = client.post(
        "/api/documents/upload",
        headers=headers,
        files={"file": ("scanned_vision.pdf", pdf_buf, "application/pdf")},
    )
    check("Upload scanned PDF succeeds (mocked Gemini)", r.status_code == 201, f"-> {r.status_code} {r.text}")
    doc_id = r.json()["id"] if r.status_code == 201 else None

    check("Exactly one vision call was made (one blank page)", len(captured_calls) == 1, f"-> {len(captured_calls)} calls")

    if captured_calls:
        call_contents = captured_calls[0]["contents"]
        parts = call_contents[0].parts
        check("Call includes an image part + a text prompt part", len(parts) == 2, f"-> {len(parts)} parts")
        image_part = parts[0]
        check(
            "Image part has correct mime_type and non-empty PNG bytes",
            image_part.inline_data.mime_type == "image/png" and len(image_part.inline_data.data) > 100,
            f"-> mime={getattr(image_part.inline_data, 'mime_type', None)}, size={len(getattr(image_part.inline_data, 'data', b''))}",
        )

    if doc_id:
        from app.core.database import SessionLocal
        from app.models.document_chunk import DocumentChunk

        db = SessionLocal()
        chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).all()
        db.close()
        check(
            "The mocked extracted text was saved as a real chunk",
            len(chunks) == 1 and "Mocked extracted text from image" in chunks[0].content,
            f"-> {[c.content for c in chunks]}",
        )

    # ========================================================
    # اختبار الإصلاح الحقيقي: رفع صورة JPG مباشرة (وليست مضمَّنة داخل PDF)
    # — هذا كان معطَّلًا بالكامل سابقًا (الشرط كان `if ext == ".pdf"` فقط).
    # ========================================================
    captured_calls.clear()
    img2 = Image.new("RGB", (400, 300), color="white")
    ImageDraw.Draw(img2).rectangle([5, 5, 395, 295], outline="black")
    jpg_buf = io.BytesIO()
    img2.save(jpg_buf, format="JPEG")
    jpg_buf.seek(0)

    r = client.post(
        "/api/documents/upload",
        headers=headers,
        files={"file": ("my_photo.jpg", jpg_buf, "image/jpeg")},
    )
    check("Upload a DIRECT JPG image (not inside a PDF) succeeds", r.status_code == 201, f"-> {r.status_code} {r.text}")
    jpg_doc_id = r.json()["id"] if r.status_code == 201 else None

    check(
        "Direct image upload triggers exactly one vision call",
        len(captured_calls) == 1,
        f"-> {len(captured_calls)} calls (this was 0 before the fix — image uploads were silently ignored)",
    )
    if captured_calls:
        image_part = captured_calls[0]["contents"][0].parts[0]
        check(
            "Direct JPG upload sends correct mime_type (image/jpeg, not png)",
            image_part.inline_data.mime_type == "image/jpeg",
            f"-> {getattr(image_part.inline_data, 'mime_type', None)}",
        )

    if jpg_doc_id:
        db = SessionLocal()
        jpg_chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == jpg_doc_id).all()
        db.close()
        check(
            "Direct JPG upload produces a real saved chunk (was always empty before the fix)",
            len(jpg_chunks) == 1,
            f"-> {len(jpg_chunks)} chunks",
        )

print()
if failures:
    print(f"❌ {len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
else:
    print("✅ ALL VISION OCR PIPELINE CHECKS PASSED")
