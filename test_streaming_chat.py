"""
اختبار endpoint البثّ الجديد /api/ai/chat/stream — يُزيّف
generate_content_stream ليُصدر عدة أجزاء نصية متتالية (محاكاة استجابة
Gemini الحقيقية المُجزَّأة)، ويتحقق أن:
1) كل الأجزاء تصل بالترتيب الصحيح بصيغة SSE سليمة.
2) النص الكامل (المُجمَّع من كل الأجزاء) يُحفَظ في قاعدة البيانات كرسالة واحدة.
3) خطأ يحدث في منتصف البثّ يصل كحدث "error" داخل التدفق، وليس كخطأ HTTP.
4) بدون مفتاح Gemini إطلاقًا، الطلب يُرفَض بـ503 *قبل* أي بثّ (ليس أثناءه).
"""
import json
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(__file__))

DB_PATH = "test_streaming.db"
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


def parse_sse_events(raw_text: str) -> list[dict]:
    events = []
    for block in raw_text.split("\n\n"):
        block = block.strip()
        if block.startswith("data: "):
            events.append(json.loads(block[len("data: "):]))
    return events


r = client.post(
    "/api/auth/register",
    json={"name": "Stream Test", "email": "streamtest@example.com", "password": "secret123"},
)
token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

# 1) بدون مفتاح إطلاقًا -> 503 حقيقي *قبل* أي بثّ.
settings.gemini_api_key = None
r = client.post("/api/ai/chat/stream", headers=headers, json={"question": "hello"})
check("Stream without API key returns 503 before streaming starts", r.status_code == 503, f"-> {r.status_code} {r.text}")
settings.gemini_api_key = "fake-key-for-mocked-test"

# 2) بث ناجح متعدد الأجزاء (محاكاة "TCP هو...", "بروتوكول...", إلخ).
fake_chunks = ["مرحبًا، ", "هذا رد ", "مُجزَّأ ", "من Gemini."]


def fake_stream_generator(*, model, contents, config):
    for text in fake_chunks:
        chunk = MagicMock()
        chunk.text = text
        yield chunk


with patch("app.services.ai_service.genai.Client") as MockClient:
    mock_instance = MagicMock()
    mock_instance.models.generate_content_stream.side_effect = fake_stream_generator
    MockClient.return_value = mock_instance

    r = client.post("/api/ai/chat/stream", headers=headers, json={"question": "What is TCP?"})
    check("Stream request succeeds (200)", r.status_code == 200, f"-> {r.status_code}")

    events = parse_sse_events(r.text)
    chunk_events = [e for e in events if e["type"] == "chunk"]
    done_events = [e for e in events if e["type"] == "done"]

    check(
        "All 4 chunks arrived in the correct order",
        [e["text"] for e in chunk_events] == fake_chunks,
        f"-> {[e.get('text') for e in chunk_events]}",
    )
    check("A 'done' event was sent at the end", len(done_events) == 1, f"-> {len(done_events)} done events")

    # التحقق أن النص الكامل (المُجمَّع) حُفظ كرسالة واحدة في قاعدة البيانات.
    r2 = client.get("/api/ai/chat/history", headers=headers)
    history = r2.json()
    assistant_messages = [m for m in history if m["role"] == "assistant"]
    check(
        "Full concatenated text saved as ONE assistant message",
        len(assistant_messages) == 1 and assistant_messages[0]["content"] == "".join(fake_chunks),
        f"-> {[m['content'] for m in assistant_messages]}",
    )

    # 3) خطأ يحدث في منتصف البثّ -> يصل كحدث "error" داخل التدفق (وليس HTTP error).
    def failing_stream_generator(*, model, contents, config):
        yield_count = 0
        for text in ["جزء أول ناجح "]:
            chunk = MagicMock()
            chunk.text = text
            yield chunk
        raise ConnectionError("انقطاع شبكي مُحاكى في المنتصف")

    mock_instance.models.generate_content_stream.side_effect = failing_stream_generator
    r3 = client.post("/api/ai/chat/stream", headers=headers, json={"question": "another question"})
    check("Mid-stream failure still returns HTTP 200 (already started)", r3.status_code == 200, f"-> {r3.status_code}")
    events3 = parse_sse_events(r3.text)
    error_events = [e for e in events3 if e["type"] == "error"]
    check(
        "Mid-stream failure produces an 'error' event inside the stream",
        len(error_events) == 1,
        f"-> events: {events3}",
    )

print()
if failures:
    print(f"❌ {len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
else:
    print("✅ ALL STREAMING CHAT CHECKS PASSED")
