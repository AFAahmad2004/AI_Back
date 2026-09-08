"""
اختبار مركّز لمنطق "ذاكرة المحادثة" — يتحقق أن السياق (الرسائل السابقة)
يُبنى ويُرسَل بشكل صحيح لواجهة Gemini، دون الحاجة لمفتاح حقيقي أو اتصال
فعلي بالشبكة (نُزيّف عميل Gemini بالكامل ونلتقط ما يُرسَل إليه فعليًا).
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(__file__))

DB_PATH = "test_memory.db"
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


# إعداد مستخدم فعلي
r = client.post(
    "/api/auth/register",
    json={"name": "Test User", "email": "memtest@example.com", "password": "secret123"},
)
token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

captured_calls = []


def fake_generate_content(*, model, contents, config):
    """يلتقط الوسائط الفعلية بدل استدعاء Gemini الحقيقي، ويُعيد ردًا وهميًا."""
    captured_calls.append({"contents": contents, "config": config})
    fake_response = MagicMock()
    fake_response.text = f"Fake answer #{len(captured_calls)}"
    return fake_response


with patch("app.services.ai_service.genai.Client") as MockClient:
    mock_instance = MagicMock()
    mock_instance.models.generate_content.side_effect = fake_generate_content
    MockClient.return_value = mock_instance

    # --- الرسالة الأولى: لا يوجد سياق سابق بعد ---
    r = client.post("/api/ai/chat", headers=headers, json={"question": "What is TCP?"})
    check("First message succeeds (mocked)", r.status_code == 200, f"-> {r.status_code} {r.text}")

    first_call_contents = captured_calls[0]["contents"]
    check(
        "First call has exactly 1 content turn (no history yet)",
        len(first_call_contents) == 1,
        f"-> {len(first_call_contents)} turns",
    )
    check(
        "First call's single turn is the user's question",
        first_call_contents[0].role == "user" and first_call_contents[0].parts[0].text == "What is TCP?",
        f"-> role={first_call_contents[0].role}, text={first_call_contents[0].parts[0].text!r}",
    )

    # --- الرسالة الثانية: يجب أن يحتوي السياق على السؤال الأول وإجابته ---
    r = client.post("/api/ai/chat", headers=headers, json={"question": "And what about UDP?"})
    check("Second message succeeds (mocked)", r.status_code == 200, f"-> {r.status_code}")

    second_call_contents = captured_calls[1]["contents"]
    check(
        "Second call includes 3 turns: prior Q, prior A, new Q",
        len(second_call_contents) == 3,
        f"-> {len(second_call_contents)} turns: {[(c.role, c.parts[0].text) for c in second_call_contents]}",
    )
    if len(second_call_contents) == 3:
        check(
            "Turn order is correct (user, model, user) with correct content",
            second_call_contents[0].role == "user"
            and second_call_contents[0].parts[0].text == "What is TCP?"
            and second_call_contents[1].role == "model"
            and second_call_contents[1].parts[0].text == "Fake answer #1"
            and second_call_contents[2].role == "user"
            and second_call_contents[2].parts[0].text == "And what about UDP?",
            f"-> {[(c.role, c.parts[0].text) for c in second_call_contents]}",
        )

    # --- التحقق أن هذا يعمل بشكل مستقل تمامًا بين محادثة عامة ومحادثة ملف ---
    # (بدون رفع ملف حقيقي هنا — فقط نتأكد أن معرّف مختلف يُنتج سياقًا منفصلًا
    #  عبر استدعاء /history مباشرة، وهو ما اختبرناه بالفعل في test_manual.py)
    r = client.get("/api/ai/chat/history", headers=headers)
    check(
        "History now shows 4 messages (2 user + 2 assistant)",
        r.status_code == 200 and len(r.json()) == 4,
        f"-> {r.json() if r.status_code == 200 else r.status_code}",
    )

print()
if failures:
    print(f"❌ {len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
else:
    print("✅ ALL CONVERSATION MEMORY CHECKS PASSED")
