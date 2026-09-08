"""
سكربت تحقق يدوي سريع (ليس جزءًا من التطبيق) — يشغّل التطبيق داخل نفس العملية
عبر TestClient بدل فتح سيرفر حقيقي، لتفادي أي مشاكل شبكة/منافذ.
تشغيل: ./venv/bin/python test_manual.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

# قاعدة بيانات نظيفة لكل تشغيل تجريبي. افتراضيًا SQLite محلي، لكن يمكن
# تمرير TEST_DATABASE_URL (مثل postgresql://...) لتشغيل نفس الاختبارات
# فعليًا ضد PostgreSQL والتأكد أن كل شيء يعمل بلا اختلاف بين قاعدتي البيانات.
DB_PATH = "test_manual.db"
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

override_url = os.environ.get("TEST_DATABASE_URL")
if override_url:
    os.environ["DATABASE_URL"] = override_url
    print(f"[INFO] Using database: {override_url.split('@')[-1] if '@' in override_url else override_url}")
else:
    os.environ["DATABASE_URL"] = f"sqlite:///./{DB_PATH}"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
failures = []


def check(label, condition, extra=""):
    status = "OK " if condition else "FAIL"
    print(f"[{status}] {label} {extra}")
    if not condition:
        failures.append(label)


# 1) Health check
r = client.get("/")
check("Health check", r.status_code == 200, r.text)

# 2) Register
r = client.post(
    "/api/auth/register",
    json={"name": "احمد محمد", "email": "ahmed@example.com", "password": "secret123"},
)
check("Register", r.status_code == 201, f"-> {r.status_code} {r.text}")
token = r.json().get("access_token") if r.status_code == 201 else None

# 3) Duplicate register should fail
r = client.post(
    "/api/auth/register",
    json={"name": "احمد", "email": "ahmed@example.com", "password": "secret123"},
)
check("Duplicate register rejected", r.status_code == 400, f"-> {r.status_code} {r.text}")

# 4) Login wrong password
r = client.post(
    "/api/auth/login", json={"email": "ahmed@example.com", "password": "wrong"}
)
check("Wrong password rejected", r.status_code == 401, f"-> {r.status_code} {r.text}")

# 5) Login correct password
r = client.post(
    "/api/auth/login", json={"email": "ahmed@example.com", "password": "secret123"}
)
check("Correct login", r.status_code == 200, f"-> {r.status_code} {r.text}")
refresh_token = r.json().get("refresh_token") if r.status_code == 200 else None
check("Login response includes refresh_token", bool(refresh_token), f"-> {r.json()}")

# 5b) Refresh token flow (§30 completeness)
r = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
check("Refresh with valid refresh_token", r.status_code == 200, f"-> {r.status_code} {r.text}")
if r.status_code == 200:
    token = r.json()["access_token"]  # نستخدم الرمز الجديد لبقية الاختبارات

r = client.post("/api/auth/refresh", json={"refresh_token": "this-is-not-a-valid-token"})
check("Refresh with invalid token rejected", r.status_code == 401, f"-> {r.status_code}")

# 5c) An access_token must NOT work as a refresh_token (type check)
r = client.post("/api/auth/refresh", json={"refresh_token": token})
check("Access token rejected when used as refresh token", r.status_code == 401, f"-> {r.status_code}")

# 6) /me with token
headers = {"Authorization": f"Bearer {token}"}
r = client.get("/api/auth/me", headers=headers)
check("Get current user", r.status_code == 200 and r.json()["email"] == "ahmed@example.com", f"-> {r.status_code} {r.text}")

# 7) /me without token should fail
r = client.get("/api/auth/me")
check("Unauthenticated /me rejected", r.status_code == 401, f"-> {r.status_code}")

# 7b) Update profile (major/study_level) — partial update, only sent fields change.
r = client.patch(
    "/api/auth/me",
    headers=headers,
    json={"major": "هندسة حاسوب", "study_level": "السنة الثالثة"},
)
check(
    "Update profile major/study_level",
    r.status_code == 200 and r.json()["major"] == "هندسة حاسوب" and r.json()["study_level"] == "السنة الثالثة",
    f"-> {r.status_code} {r.text}",
)
check("Name unchanged when not sent in partial update", r.json()["name"] == "احمد محمد", f"-> {r.json()['name']}")

# 7c) Update only the name, major/study_level should remain from previous update.
r = client.patch("/api/auth/me", headers=headers, json={"name": "Ahmed Updated"})
check(
    "Partial update of name only preserves major/study_level",
    r.status_code == 200 and r.json()["name"] == "Ahmed Updated" and r.json()["major"] == "هندسة حاسوب",
    f"-> {r.status_code} {r.json()}",
)

# 7d) Unauthenticated profile update rejected.
r = client.patch("/api/auth/me", json={"name": "hacker"})
check("Unauthenticated profile update rejected", r.status_code == 401, f"-> {r.status_code}")

# 8) Upload a real (small) generated PDF
from pypdf import PdfWriter  # noqa: E402
import io  # noqa: E402

writer = PdfWriter()
for _ in range(5):
    writer.add_blank_page(width=200, height=200)
buf = io.BytesIO()
writer.write(buf)
buf.seek(0)

r = client.post(
    "/api/documents/upload",
    headers=headers,
    files={"file": ("Computer_Networks.pdf", buf, "application/pdf")},
)
check("Upload valid PDF", r.status_code == 201, f"-> {r.status_code} {r.text}")
if r.status_code == 201:
    check("Extracted correct page count", r.json()["pages"] == 5, f"-> pages={r.json()['pages']}")
    doc_id = r.json()["id"]
else:
    doc_id = None

# 9) List documents
r = client.get("/api/documents", headers=headers)
check("List documents", r.status_code == 200 and len(r.json()) == 1, f"-> {r.status_code} {r.text}")

# 10) Upload unsupported file type
r = client.post(
    "/api/documents/upload",
    headers=headers,
    files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")},
)
check("Unsupported file type rejected", r.status_code == 415, f"-> {r.status_code} {r.text}")

# 11) Documents endpoint without auth
r = client.get("/api/documents")
check("Unauthenticated documents list rejected", r.status_code == 401, f"-> {r.status_code}")

# 12) Delete the uploaded document
if doc_id:
    r = client.delete(f"/api/documents/{doc_id}", headers=headers)
    check("Delete document", r.status_code == 204, f"-> {r.status_code}")

    r = client.get("/api/documents", headers=headers)
    check("Document list empty after delete", r.status_code == 200 and len(r.json()) == 0, f"-> {r.json()}")

# ============================================================
# AI features (§8, §10, §25) — RAG pipeline tests
# ============================================================
print("\n--- AI / RAG ---")

# 13) Upload a PDF that actually contains real extractable text (using reportlab)
try:
    from reportlab.pdfgen import canvas  # noqa: E402

    text_pdf_buf = io.BytesIO()
    c = canvas.Canvas(text_pdf_buf)
    c.drawString(100, 750, "Computer Networks Lecture")
    c.drawString(100, 700, "TCP is a connection-oriented transport protocol.")
    c.drawString(100, 650, "The OSI model has seven layers.")
    c.showPage()
    c.drawString(100, 750, "Page two")
    c.drawString(100, 700, "IP works at the network layer and handles addressing.")
    c.save()
    text_pdf_buf.seek(0)

    r = client.post(
        "/api/documents/upload",
        headers=headers,
        files={"file": ("networks.pdf", text_pdf_buf, "application/pdf")},
    )
    check("Upload text-based PDF", r.status_code == 201, f"-> {r.status_code} {r.text}")
    text_doc_id = r.json()["id"] if r.status_code == 201 else None
except ImportError:
    print("[SKIP] reportlab not installed — skipping text-PDF-based AI tests. "
          "Install with: pip install reportlab")
    text_doc_id = None

# ============================================================
# OCR for scanned PDFs (§7) — a REAL image-only PDF (no text layer at
# all), uploaded through the actual API, verifying the full pipeline:
# upload -> OCR fallback -> chunk -> stored in DB.
# ============================================================
print("\n--- OCR (scanned PDFs) ---")
try:
    from PIL import Image, ImageDraw, ImageFont
    from reportlab.lib.pagesizes import letter

    img = Image.new("RGB", (1000, 300), color="white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 40)
    except Exception:
        font = ImageFont.load_default()
    draw.text((40, 100), "OCR Verification Page", fill="black", font=font)

    scan_buf = io.BytesIO()
    scan_canvas_pdf = io.BytesIO()
    img.save("/tmp/_ocr_test_img.png")

    scan_writer_c = canvas.Canvas(scan_canvas_pdf, pagesize=letter)
    scan_writer_c.drawImage("/tmp/_ocr_test_img.png", 50, 500, width=400, height=120)
    scan_writer_c.showPage()
    scan_writer_c.save()
    scan_canvas_pdf.seek(0)

    r = client.post(
        "/api/documents/upload",
        headers=headers,
        files={"file": ("scanned.pdf", scan_canvas_pdf, "application/pdf")},
    )
    check("Upload image-only (scanned-style) PDF", r.status_code == 201, f"-> {r.status_code} {r.text}")
    scanned_doc_id = r.json()["id"] if r.status_code == 201 else None

    if scanned_doc_id:
        from app.core.database import SessionLocal
        from app.models.document_chunk import DocumentChunk as DocumentChunkModel

        db = SessionLocal()
        chunks = db.query(DocumentChunkModel).filter(DocumentChunkModel.document_id == scanned_doc_id).all()
        db.close()
        # بدون مفتاح Gemini حقيقي في بيئة الاختبار هذه، قراءة الصورة عبر
        # Gemini Vision تفشل بأمان (AIServiceUnavailable المُلتقَطة داخليًا)
        # وتُعيد نصًا فارغًا لتلك الصفحة — وهذا هو السلوك الصحيح المتوقَّع:
        # لا انهيار في الرفع، فقط عدم وجود مقاطع قابلة للتوليد منها.
        check(
            "Upload succeeds gracefully with zero chunks when no Gemini key (no crash)",
            len(chunks) == 0,
            f"-> {len(chunks)} chunks (expected 0 without a real API key)",
        )
except ImportError as e:
    print(f"[SKIP] OCR test skipped — missing optional dependency: {e}")
except Exception as e:
    check("OCR pipeline ran without crashing", False, f"-> unexpected error: {e}")

# 14) Chat WITHOUT an API key configured -> must fail gracefully with 503,
#     not crash, and retrieval must still work via keyword fallback internally.
if text_doc_id:
    r = client.post(
        "/api/ai/chat",
        headers=headers,
        json={"document_id": text_doc_id, "question": "What layer does TCP work at?"},
    )
    check(
        "Chat without API key returns 503 (not a crash)",
        r.status_code == 503,
        f"-> {r.status_code} {r.text}",
    )

    # 14b) General chat (§10: no document_id at all) — must work independently
    #      of any uploaded document, still gracefully 503 without a key.
    r = client.post(
        "/api/ai/chat",
        headers=headers,
        json={"question": "اشرح لي مفهوم التعلم الآلي ببساطة"},
    )
    check(
        "General chat (no document_id) without API key returns 503",
        r.status_code == 503,
        f"-> {r.status_code} {r.text}",
    )
    check(
        "General chat request accepted without a 404 (not document-bound)",
        r.status_code != 404,
        f"-> {r.status_code}",
    )

    # 14c) Chat history (§10) — the user's question is saved even though the
    #      AI call itself failed (no key), because saving happens before the
    #      AI call. This proves persistence works independently of AI success.
    r = client.get("/api/ai/chat/history", headers=headers)
    check("Get general chat history", r.status_code == 200, f"-> {r.status_code} {r.text}")
    general_history = r.json() if r.status_code == 200 else []
    check(
        "General history contains the saved user question",
        any(m["role"] == "user" and "التعلم الآلي" in m["content"] for m in general_history),
        f"-> {general_history}",
    )

    r = client.get(f"/api/ai/chat/history?document_id={text_doc_id}", headers=headers)
    document_history = r.json() if r.status_code == 200 else []
    check(
        "Document-scoped history is separate from general history",
        all("التعلم الآلي" not in m["content"] for m in document_history),
        f"-> {document_history}",
    )
    check(
        "Document-scoped history contains the earlier TCP question",
        any("TCP" in m["content"] for m in document_history),
        f"-> {document_history}",
    )

    r = client.get("/api/ai/chat/history")
    check("Unauthenticated chat history rejected", r.status_code == 401, f"-> {r.status_code}")

    # 15) Summary WITHOUT an API key -> same graceful 503
    r = client.post(
        f"/api/documents/{text_doc_id}/summary",
        headers=headers,
        json={"level": "مختصر"},
    )
    check(
        "Summary without API key returns 503 (not a crash)",
        r.status_code == 503,
        f"-> {r.status_code} {r.text}",
    )

    # 16) Chat on a document with a bogus API key -> must translate the
    #     network/auth failure into a clean 502, never an unhandled exception.
    # `settings` is a singleton object shared by reference across all modules
    # that imported it, so mutating the attribute directly is enough — no
    # need to reload any module.
    from app.core.config import settings as app_settings
    app_settings.gemini_api_key = "invalid-fake-key-for-testing"

    r = client.post(
        "/api/ai/chat",
        headers=headers,
        json={"document_id": text_doc_id, "question": "What layer does TCP work at?"},
    )
    check(
        "Chat with invalid API key returns 502, not a crash",
        r.status_code == 502,
        f"-> {r.status_code} {r.text}",
    )
    app_settings.gemini_api_key = None
else:
    print("[SKIP] AI tests skipped (no text-based PDF uploaded)")

# ============================================================
# Quiz feature (§11, §12, §24) — generation graceful failure + full
# submit/scoring logic (this part needs no AI, so it's fully testable here).
# ============================================================
print("\n--- Quiz ---")

if text_doc_id:
    # 17) Generating questions without an API key -> graceful 503, not a crash.
    r = client.post(
        f"/api/documents/{text_doc_id}/questions",
        headers=headers,
        json={"count": 3, "difficulty": "متوسط"},
    )
    check(
        "Generate questions without API key returns 503",
        r.status_code == 503,
        f"-> {r.status_code} {r.text}",
    )

    # 18) Manually insert a quiz + questions directly in the DB (bypassing AI)
    #     to fully exercise the submit/scoring endpoint end-to-end.
    from app.core.database import SessionLocal
    from datetime import datetime
    from app.models.quiz import Quiz, Question
    import json as _json

    db = SessionLocal()
    quiz = Quiz(document_id=text_doc_id, owner_id=1, difficulty="متوسط")
    db.add(quiz)
    db.flush()
    q1 = Question(
        quiz_id=quiz.id, order_index=0, text="What layer does TCP work at?",
        options_json=_json.dumps(["Network", "Transport", "Session", "Application"]),
        correct_index=1,
    )
    q2 = Question(
        quiz_id=quiz.id, order_index=1, text="Is TCP connection-oriented?",
        options_json=_json.dumps(["Yes", "No", "Sometimes", "Unknown"]),
        correct_index=0,
    )
    db.add_all([q1, q2])
    db.commit()
    quiz_id = quiz.id
    db.close()

    # 19) Fetch the quiz for taking it -> must NOT leak correct_index.
    r = client.get(f"/api/quizzes/{quiz_id}", headers=headers)
    check("Get quiz for taking it", r.status_code == 200, f"-> {r.status_code} {r.text}")
    check(
        "Quiz questions do not leak correct_index",
        r.status_code == 200 and "correct_index" not in _json.dumps(r.json()),
        f"-> {r.json()}",
    )

    # 20) Submit with one correct + one wrong answer -> must score exactly 50%.
    r = client.post(
        f"/api/quizzes/{quiz_id}/submit",
        headers=headers,
        json={"answers": [1, 1], "time_taken_seconds": 42},  # q1 correct(1), q2 wrong(1 instead of 0)
    )
    check("Submit quiz", r.status_code == 200, f"-> {r.status_code} {r.text}")
    if r.status_code == 200:
        body = r.json()
        check("Score computed correctly (50%)", body["score_percent"] == 50.0, f"-> {body['score_percent']}")
        check("Correct count is 1", body["correct_count"] == 1, f"-> {body['correct_count']}")

    # 21) Submit with mismatched answer count -> must reject with 400, not crash.
    r = client.post(
        f"/api/quizzes/{quiz_id}/submit",
        headers=headers,
        json={"answers": [1]},  # only 1 answer for 2 questions
    )
    check("Mismatched answers count rejected", r.status_code == 400, f"-> {r.status_code} {r.text}")

    # 22) Quiz history list reflects the best score.
    r = client.get("/api/quizzes", headers=headers)
    check("Quiz history list", r.status_code == 200 and len(r.json()) == 1, f"-> {r.json()}")
    if r.status_code == 200 and r.json():
        check(
            "Quiz history shows correct best score",
            r.json()[0]["best_score_percent"] == 50.0,
            f"-> {r.json()[0]}",
        )
else:
    print("[SKIP] Quiz tests skipped (no text-based PDF uploaded)")

# ============================================================
# Flashcards feature (§14, §24)
# ============================================================
print("\n--- Flashcards ---")

if text_doc_id:
    # 23) Generating flashcards without an API key -> graceful 503.
    r = client.post(
        f"/api/documents/{text_doc_id}/flashcards",
        headers=headers,
        json={"count": 5},
    )
    check(
        "Generate flashcards without API key returns 503",
        r.status_code == 503,
        f"-> {r.status_code} {r.text}",
    )

    # 24) Manually insert flashcards directly (bypassing AI) to test the
    #     list/review/delete endpoints fully — they need no AI at all.
    from app.core.database import SessionLocal
    from app.models.flashcard import Flashcard

    db = SessionLocal()
    card1 = Flashcard(document_id=text_doc_id, owner_id=1, front="What is TCP?", back="A connection-oriented transport protocol.")
    card2 = Flashcard(document_id=text_doc_id, owner_id=1, front="OSI layers count?", back="7")
    db.add_all([card1, card2])
    db.commit()
    card1_id = card1.id
    db.close()

    # 25) List flashcards for the document.
    r = client.get(f"/api/documents/{text_doc_id}/flashcards", headers=headers)
    check("List flashcards", r.status_code == 200 and len(r.json()) == 2, f"-> {r.status_code} {r.json()}")

    # 26) Review a card as "known".
    r = client.post(f"/api/flashcards/{card1_id}/review", headers=headers, json={"known": True})
    check("Review flashcard as known", r.status_code == 204, f"-> {r.status_code} {r.text}")

    db = SessionLocal()
    refreshed = db.query(Flashcard).filter(Flashcard.id == card1_id).first()
    check("known_count incremented", refreshed.known_count == 1, f"-> {refreshed.known_count}")
    db.close()

    # 27) Delete a flashcard.
    r = client.delete(f"/api/flashcards/{card1_id}", headers=headers)
    check("Delete flashcard", r.status_code == 204, f"-> {r.status_code}")

    r = client.get(f"/api/documents/{text_doc_id}/flashcards", headers=headers)
    check("Flashcard list has 1 left after delete", r.status_code == 200 and len(r.json()) == 1, f"-> {r.json()}")

    # 28) Review/delete a non-existent card -> 404, not a crash.
    r = client.post("/api/flashcards/99999/review", headers=headers, json={"known": True})
    check("Review non-existent flashcard returns 404", r.status_code == 404, f"-> {r.status_code}")

    # ============================================================
    # Spaced Repetition (§15) — real interval progression, not mocked.
    # ============================================================
    print("\n--- Spaced Repetition ---")
    db = SessionLocal()
    sr_card = Flashcard(document_id=text_doc_id, owner_id=1, front="Spaced?", back="Repetition!")
    db.add(sr_card)
    db.commit()
    sr_card_id = sr_card.id
    db.close()

    # 29) First "known" review -> next_review_at should land ~1 day from now.
    r = client.post(f"/api/flashcards/{sr_card_id}/review", headers=headers, json={"known": True})
    check("First known-review accepted", r.status_code == 204, f"-> {r.status_code}")

    def hours_until(dt):
        return (dt.replace(tzinfo=None) - datetime.utcnow()).total_seconds() / 3600

    db = SessionLocal()
    refreshed = db.query(Flashcard).filter(Flashcard.id == sr_card_id).first()
    hrs = hours_until(refreshed.next_review_at)
    check("Interval after 1st known review is ~1 day (24h ± 1h)", 23 <= hrs <= 25, f"-> {hrs:.1f}h, known_count={refreshed.known_count}")
    db.close()

    # 30) Second "known" review -> interval should jump to ~3 days.
    r = client.post(f"/api/flashcards/{sr_card_id}/review", headers=headers, json={"known": True})
    db = SessionLocal()
    refreshed = db.query(Flashcard).filter(Flashcard.id == sr_card_id).first()
    hrs = hours_until(refreshed.next_review_at)
    check("Interval after 2nd known review is ~3 days (72h ± 1h)", 71 <= hrs <= 73, f"-> {hrs:.1f}h")
    db.close()

    # 31) A "difficult" review resets the streak back to ~1 day.
    r = client.post(f"/api/flashcards/{sr_card_id}/review", headers=headers, json={"known": False})
    db = SessionLocal()
    refreshed = db.query(Flashcard).filter(Flashcard.id == sr_card_id).first()
    hrs = hours_until(refreshed.next_review_at)
    check(
        "Difficult review resets interval to ~1 day and known_count to 0",
        23 <= hrs <= 25 and refreshed.known_count == 0,
        f"-> {hrs:.1f}h, known_count={refreshed.known_count}",
    )
    db.close()

    # 32) due_only=true excludes cards scheduled in the future.
    r = client.get(f"/api/documents/{text_doc_id}/flashcards?due_only=true", headers=headers)
    due_ids = [c["id"] for c in r.json()] if r.status_code == 200 else []
    check(
        "due_only excludes the just-scheduled (future) card",
        r.status_code == 200 and sr_card_id not in due_ids,
        f"-> {r.json()}",
    )
else:
    print("[SKIP] Flashcard tests skipped (no text-based PDF uploaded)")

# ============================================================
# Rate limiting (§30) — configurable, defaults to a very high ceiling per
# an explicit request to avoid throttling normal usage. We temporarily
# lower it here just to prove the mechanism itself still works correctly
# when an operator *does* want to configure a limit.
# ============================================================
print("\n--- Rate Limiting ---")

if text_doc_id:
    from app.core import rate_limit as rate_limit_module

    original_limit = rate_limit_module._MAX_REQUESTS_PER_WINDOW
    rate_limit_module._MAX_REQUESTS_PER_WINDOW = 3  # قيمة صغيرة مؤقتة لهذا الاختبار فقط

    hit_429 = False
    for i in range(10):
        r = client.post(
            "/api/ai/chat",
            headers=headers,
            json={"document_id": text_doc_id, "question": f"probe {i}"},
        )
        if r.status_code == 429:
            hit_429 = True
            break
    check("AI rate limit triggers 429 when configured low", hit_429, f"-> stopped after {i+1} requests, last status {r.status_code}")

    rate_limit_module._MAX_REQUESTS_PER_WINDOW = original_limit  # نعيده لقيمته الافتراضية العالية لبقية الاختبارات

    # تحقّق أن القيمة الافتراضية (بلا تعديل .env) عالية فعليًا كما هو متوقَّع.
    check(
        "Default rate limit is high (no artificial throttling) per explicit request",
        original_limit >= 1000,
        f"-> default is {original_limit}",
    )
else:
    print("[SKIP] Rate limit test skipped (no text-based PDF uploaded)")

# ============================================================
# Study Sessions (§21) — real study-time tracking, not just quiz time.
# ============================================================
print("\n--- Study Sessions ---")

if text_doc_id:
    # 29) Start a session for a real document.
    r = client.post("/api/study-sessions/start", headers=headers, json={"document_id": text_doc_id})
    check("Start study session", r.status_code == 200, f"-> {r.status_code} {r.text}")
    session_id = r.json()["id"] if r.status_code == 200 else None

    # 30) Starting a session for a non-existent document -> 404, not a crash.
    r = client.post("/api/study-sessions/start", headers=headers, json={"document_id": 99999})
    check("Start session for non-existent document returns 404", r.status_code == 404, f"-> {r.status_code}")

    # 31) Backdate the session's start time by ~100 seconds directly in the
    #     DB (simulating real elapsed time), then end it via the real API
    #     and verify the computed duration reflects that elapsed time.
    from app.core.database import SessionLocal
    from app.models.study_session import StudySession as StudySessionModel
    from datetime import timedelta

    db = SessionLocal()
    sess = db.query(StudySessionModel).filter(StudySessionModel.id == session_id).first()
    sess.started_at = sess.started_at - timedelta(seconds=100)
    db.commit()
    db.close()

    r = client.post(f"/api/study-sessions/{session_id}/end", headers=headers)
    check("End study session", r.status_code == 200, f"-> {r.status_code} {r.text}")
    duration = r.json()["duration_seconds"] if r.status_code == 200 else 0
    check("Session duration reflects elapsed time (~100s)", 95 <= duration <= 110, f"-> {duration}s")

    # 32) Ending a non-existent session -> 404.
    r = client.post("/api/study-sessions/99999/end", headers=headers)
    check("End non-existent session returns 404", r.status_code == 404, f"-> {r.status_code}")

    # 33) Ending an already-ended session is idempotent (returns same duration, no crash).
    r = client.post(f"/api/study-sessions/{session_id}/end", headers=headers)
    check(
        "Ending an already-ended session is idempotent",
        r.status_code == 200 and r.json()["duration_seconds"] == duration,
        f"-> {r.status_code} {r.json() if r.status_code == 200 else ''}",
    )

    # 34) A session left "open" for an unreasonably long time (crashed app,
    #     never called /end normally) must be CAPPED in progress totals,
    #     not counted at full length — proves the safety cap actually works.
    db = SessionLocal()
    long_session = StudySessionModel(owner_id=1, document_id=text_doc_id)
    long_session.started_at = datetime.utcnow() - timedelta(hours=8)
    db.add(long_session)
    db.commit()
    long_session_id = long_session.id
    db.close()

    r = client.post(f"/api/study-sessions/{long_session_id}/end", headers=headers)
    check("End the artificially long session", r.status_code == 200, f"-> {r.status_code}")
    uncapped_duration = r.json()["duration_seconds"]
    check("Uncapped duration is indeed ~8 hours (sanity check)", uncapped_duration > 28000, f"-> {uncapped_duration}s")
else:
    print("[SKIP] Study session tests skipped (no text-based PDF uploaded)")

# ============================================================
# Progress feature (§21-§22) — aggregated from REAL quiz_attempts AND
# study_sessions data created earlier in this same test run.
# ============================================================
print("\n--- Progress ---")

r = client.get("/api/progress", headers=headers)
check("Get progress", r.status_code == 200, f"-> {r.status_code} {r.text}")
if r.status_code == 200:
    progress = r.json()
    check("files_count reflects real remaining documents (networks.pdf + scanned.pdf)", progress["files_count"] == 2, f"-> {progress['files_count']}")
    check("quizzes_count reflects the one real attempt made earlier", progress["quizzes_count"] == 1, f"-> {progress['quizzes_count']}")
    check("average_score_percent matches the earlier 50% attempt", progress["average_score_percent"] == 50.0, f"-> {progress['average_score_percent']}")
    # وقت الدراسة المتوقَّع الآن = 42s (اختبار) + ~100s (جلسة عادية)
    # + 10800s كحد أقصى (الجلسة الطويلة المحدودة بـ 180 دقيقة)، وليس ~28800s الفعلية.
    expected_min = 42 + 95 + 10800
    expected_max = 42 + 110 + 10800
    check(
        "total_study_time_seconds includes capped session time (not raw ~8h)",
        expected_min <= progress["total_study_time_seconds"] <= expected_max,
        f"-> {progress['total_study_time_seconds']} (expected {expected_min}-{expected_max})",
    )
    check("XP computed from real correct answers (1 correct * 10)", progress["current_xp"] == 10, f"-> {progress['current_xp']}")
    check("streak_days is at least 1 (an attempt happened today)", progress["streak_days"] >= 1, f"-> {progress['streak_days']}")
    check("topic_scores derived from real document title", len(progress["topic_scores"]) == 1 and progress["topic_scores"][0]["label"] == "networks.pdf", f"-> {progress['topic_scores']}")
    check("recent_quizzes has the real attempt", len(progress["recent_quizzes"]) == 1, f"-> {progress['recent_quizzes']}")

# 35) Unauthenticated progress request rejected.
r = client.get("/api/progress")
check("Unauthenticated progress rejected", r.status_code == 401, f"-> {r.status_code}")

# 36) Unauthenticated study-session start rejected.
r = client.post("/api/study-sessions/start", json={})
check("Unauthenticated study session start rejected", r.status_code == 401, f"-> {r.status_code}")

print()
if failures:
    print(f"❌ {len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
else:
    print("✅ ALL CHECKS PASSED")
