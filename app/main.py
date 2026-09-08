import os

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, inspect

from app.core.config import settings
from app.models import chat_message, document, document_chunk, flashcard, quiz, study_session, user  # noqa: F401  (تُسجَّل الجداول عند الاستيراد)
from app.routers import auth, documents, ai, quizzes, flashcards as flashcards_router, progress, study_sessions

# ⚠️ الحل الدائم لمشكلة "no such column" المتكرّرة: بدل create_all (الذي
# ينشئ الجداول المفقودة فقط، ولا يُحدّث أعمدة جديدة على جدول موجود
# بالفعل)، نُطبّق Alembic تلقائيًا عند كل بدء تشغيل. أي تعديل مستقبلي على
# النماذج (عمود جديد، جدول جديد...) سيُطبَّق تلقائيًا هنا بمجرد إضافة
# Migration له عبر `alembic revision --autogenerate` — بدون أي خطوة يدوية
# من المستخدم، وبدون حذف قاعدة البيانات أبدًا.
_ALEMBIC_INI_PATH = os.path.join(os.path.dirname(__file__), "..", "alembic.ini")

# أول Migration في المشروع (المخطط الأساسي، قبل أي إضافات مثل google_id).
# يُستخدم فقط لـ"تعليم" قواعد بيانات قديمة أُنشئت عبر create_all القديم
# (قبل اعتماد Alembic في هذا المشروع) — راجع _run_migrations أدناه.
_INITIAL_REVISION = "de243357a7fa"


def _run_migrations() -> None:
    alembic_cfg = Config(_ALEMBIC_INI_PATH)

    engine = create_engine(settings.database_url)
    existing_tables = inspect(engine).get_table_names()
    engine.dispose()

    if "alembic_version" not in existing_tables and "users" in existing_tables:
        # قاعدة بيانات موجودة مسبقًا أُنشئت عبر create_all القديم (قبل
        # اعتماد Alembic في هذا المشروع) — جداولها الأساسية موجودة فعلًا
        # لكن Alembic لا "يعرف" ذلك بعد. تشغيل upgrade مباشرة سيحاول
        # إعادة إنشائها من الصفر ويفشل بخطأ "table already exists".
        # الحل: نُعلِّم (stamp) قاعدة البيانات عند أول Migration بدون
        # تنفيذه فعليًا (لأن جداوله موجودة أصلًا)، ثم upgrade head تُكمل
        # من هناك فتُطبَّق فقط الـ Migrations الجديدة (مثل إضافة google_id).
        command.stamp(alembic_cfg, _INITIAL_REVISION)

    command.upgrade(alembic_cfg, "head")


_run_migrations()

app = FastAPI(
    title="AI Study Assistant API",
    description="Backend أساسي لتطبيق مساعد الدراسة الذكي — Auth + رفع الملفات (المرحلة 1).",
    version="0.1.0",
)

# CORS مفتوح هنا لتسهيل التطوير المحلي فقط — يجب تقييده لدومينات محددة في الإنتاج.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(ai.router)
app.include_router(quizzes.router)
app.include_router(flashcards_router.router)
app.include_router(progress.router)
app.include_router(study_sessions.router)


@app.get("/", tags=["Health"])
def health_check():
    return {"status": "ok", "service": "ai-study-assistant-api"}
