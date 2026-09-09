"""
يتحقق رقميًا (وليس افتراضًا) أن /api/progress لا يعاني من مشكلة N+1
استعلام بعد إضافة joinedload — عبر عدّ الاستعلامات الفعلية المُنفَّذة على
قاعدة البيانات باستخدام أحداث SQLAlchemy، مع عدة محاولات اختبار حقيقية.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

DB_PATH = "test_perf.db"
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
os.environ["DATABASE_URL"] = f"sqlite:///./{DB_PATH}"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.core.database import engine, SessionLocal  # noqa: E402
from app.models.quiz import Quiz, Question, QuizAttempt  # noqa: E402
from sqlalchemy import event  # noqa: E402

client = TestClient(app)
failures = []


def check(label, condition, extra=""):
    status = "OK " if condition else "FAIL"
    print(f"[{status}] {label} {extra}")
    if not condition:
        failures.append(label)


r = client.post(
    "/api/auth/register",
    json={"name": "Perf Test", "email": "perftest@example.com", "password": "secret123"},
)
token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# إنشاء ملف واحد (Document) وربط 20 اختبارًا منفصلًا به، كل واحد بمحاولة
# (QuizAttempt) واحدة — يحاكي مستخدمًا نشيطًا له سجل اختبارات طويل نسبيًا.
from app.models.document import Document  # noqa: E402

db = SessionLocal()
doc = Document(owner_id=1, title="perf.pdf", folder="ملفات جديدة", file_path="/tmp/x", file_type="pdf", pages=1)
db.add(doc)
db.flush()
doc_id = doc.id
for i in range(20):
    quiz = Quiz(document_id=doc_id, owner_id=1, difficulty="متوسط")
    db.add(quiz)
    db.flush()
    q = Question(
        quiz_id=quiz.id, order_index=0, text="Q", options_json="[]", correct_index=0,
    )
    db.add(q)
    db.flush()
    attempt = QuizAttempt(
        quiz_id=quiz.id, owner_id=1, correct_count=1, total_count=1,
        score_percent=100.0, time_taken_seconds=10,
    )
    db.add(attempt)
db.commit()
db.close()

# عدّاد استعلامات فعلي عبر حدث SQLAlchemy (يُسجَّل عند كل تنفيذ SQL حقيقي).
query_count = 0


def _count_queries(*args, **kwargs):
    global query_count
    query_count += 1


event.listen(engine, "before_cursor_execute", _count_queries)

query_count = 0
r = client.get("/api/progress", headers=headers)
total_queries = query_count

event.remove(engine, "before_cursor_execute", _count_queries)

check("Progress endpoint succeeds with 20 quiz attempts", r.status_code == 200, f"-> {r.status_code}")
check(
    "Query count stays low (no N+1) — under 10 queries for 20 attempts",
    total_queries < 10,
    f"-> {total_queries} actual SQL queries executed for 20 attempts "
    f"(N+1 pattern would need ~41+: 1 base + 20 quiz + 20 document)",
)

print()
if failures:
    print(f"❌ {len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
else:
    print("✅ N+1 QUERY FIX VERIFIED")
