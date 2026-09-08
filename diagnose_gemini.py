"""
سكربت تشخيص سريع لمعرفة سبب فشل استدعاء Gemini الفعلي — يطبع الخطأ
الحقيقي الكامل بدل الرسالة العامة "تعذّر الاتصال بخدمة الذكاء الاصطناعي".

التشغيل (من مجلد ai_study_backend، مع تفعيل venv):
    python diagnose_gemini.py
"""
import os
import sys

# يقرأ GEMINI_API_KEY من .env تلقائيًا (نفس طريقة قراءة التطبيق الفعلي)
from dotenv import load_dotenv
load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
print(f"المفتاح المقروء من .env: {api_key[:10]}...{api_key[-4:] if api_key else '(غير موجود!)'}")

if not api_key:
    print("❌ GEMINI_API_KEY غير موجود في .env — تأكد من وجود السطر فيه.")
    sys.exit(1)

from google import genai
from google.genai import types

client = genai.Client(api_key=api_key)

print("\n--- محاولة استدعاء فعلي لـ generate_content (gemini-3.6-flash) ---")
try:
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents="قل مرحبًا بجملة واحدة قصيرة.",
        config=types.GenerateContentConfig(temperature=0.3),
    )
    print("✅ نجح الاستدعاء!")
    print("الرد:", response.text)
except Exception as e:
    print(f"❌ فشل الاستدعاء. نوع الخطأ: {type(e).__name__}")
    print(f"تفاصيل الخطأ الكاملة:\n{e}")

print("\n--- محاولة استدعاء فعلي لـ embed_content (text-embedding-004) ---")
try:
    embed_response = client.models.embed_content(
        model="text-embedding-004",
        contents="نص تجريبي للتحقق من عمل الـ Embeddings.",
        config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
    )
    print(f"✅ نجح استدعاء Embeddings! (طول المتجه: {len(embed_response.embeddings[0].values)})")
except Exception as e:
    print(f"❌ فشل استدعاء Embeddings. نوع الخطأ: {type(e).__name__}")
    print(f"تفاصيل الخطأ الكاملة:\n{e}")
