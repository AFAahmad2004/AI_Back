import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import rate_limit_ai
from app.core.security import get_current_user
from app.models.chat_message import ChatMessage
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.user import User
from app.schemas.ai import ChatRequest, ChatResponse, ChatSource, ChatHistoryMessage
from app.services.ai_service import (
    AIServiceUnavailable,
    AIServiceError,
    chat_completion,
    chat_completion_stream,
)
from app.services.retrieval import retrieve_relevant_chunks

router = APIRouter(prefix="/api/ai", tags=["AI"])

# عدد رسائل السياق السابقة المُرسَلة مع كل سؤال جديد — رقم صغير يوازن بين
# "تذكّر" مفيد للمحادثة وبين تكلفة/زمن استجابة إضافيَّين لكل طلب.
MAX_HISTORY_MESSAGES = 10

DOCUMENT_SYSTEM_PROMPT = (
    "أنت مساعد دراسي ذكي. أجب على سؤال الطالب بالاعتماد فقط على المحتوى "
    "المرفق من محاضرته أدناه. إذا لم يكن الجواب موجودًا في المحتوى، صرّح "
    "بذلك بوضوح بدل تأليف إجابة من معرفتك العامة. أجب باللغة العربية "
    "بإيجاز ووضوح. نسّق إجابتك بصيغة Markdown عند الحاجة: **تشديد** "
    "للمصطلحات المهمة، قوائم نقطية للتعداد، وعناوين قصيرة (##) عند تقسيم "
    "إجابة طويلة لأقسام — هذا يُعرَض فعليًا منسَّقًا في التطبيق."
)

# محادثة عامة (§10: "اسأل AI" بلا رفع ملف) — لا RAG، لا مقاطع، إجابة من
# معرفة النموذج العامة مباشرة، بنفس شخصية "مساعد دراسي" حفاظًا على تجربة
# موحّدة سواء كانت المحادثة مرتبطة بمحاضرة أو لا.
GENERAL_SYSTEM_PROMPT = (
    "أنت مساعد دراسي ذكي يساعد الطلاب في فهم أي مادة أو مفهوم دراسي. "
    "أجب بوضوح وإيجاز باللغة العربية، وقدّم أمثلة عند الحاجة لتسهيل الفهم. "
    "نسّق إجابتك بصيغة Markdown عند الحاجة: **تشديد** للمصطلحات المهمة، "
    "قوائم نقطية للتعداد، وعناوين قصيرة (##) عند تقسيم إجابة طويلة لأقسام "
    "— هذا يُعرَض فعليًا منسَّقًا في التطبيق."
)


def _save_message(db: Session, owner_id: int, document_id: int | None, role: str, content: str) -> None:
    db.add(ChatMessage(owner_id=owner_id, document_id=document_id, role=role, content=content))
    db.commit()


def _recent_history(db: Session, owner_id: int, document_id: int | None) -> list[dict]:
    """يجلب آخر MAX_HISTORY_MESSAGES رسالة من هذه المحادثة (بالترتيب
    الزمني الصحيح: الأقدم أولًا) لتُستخدم كسياق فعلي في السؤال التالي —
    هذا ما يمنح المحادثة "ذاكرة" حقيقية بدل معاملة كل سؤال بمعزل عن سابقه."""
    query = db.query(ChatMessage).filter(ChatMessage.owner_id == owner_id)
    if document_id is None:
        query = query.filter(ChatMessage.document_id.is_(None))
    else:
        query = query.filter(ChatMessage.document_id == document_id)

    recent = (
        query.order_by(ChatMessage.created_at.desc()).limit(MAX_HISTORY_MESSAGES).all()
    )
    recent.reverse()  # أقدم أولًا، كما يتوقّع chat_completion
    return [{"role": m.role, "content": m.content} for m in recent]


def _sse_event(data: dict) -> str:
    """يُنسّق حدثًا واحدًا بصيغة Server-Sent Events القياسية (§10 streaming).
    كل حدث سطر JSON واحد مسبوق بـ`data: ` ومنتهٍ بسطرين فارغين — Flutter
    يقرأ هذا التنسيق مباشرة (`http` package يدعم قراءة الاستجابة كـ Stream)."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _prepare_chat_context(payload: ChatRequest, current_user: User, db: Session):
    """يُحضّر كل ما تحتاجه المحادثة (عامة أو RAG) قبل استدعاء AI فعليًا:
    يتحقق من الملف إن وُجد، يبني الـ Prompt والسياق، ويحفظ سؤال المستخدم
    فورًا (بغض النظر عن نجاح استدعاء AI لاحقًا). يُستخدَم من كل من نسخة
    /chat العادية و/chat/stream البثّية لتفادي تكرار نفس المنطق مرتين."""
    if payload.document_id is None:
        history = _recent_history(db, current_user.id, None)
        _save_message(db, current_user.id, None, "user", payload.question)
        return GENERAL_SYSTEM_PROMPT, payload.question, history, None, "general", None

    doc = (
        db.query(Document)
        .filter(Document.id == payload.document_id, Document.owner_id == current_user.id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="الملف غير موجود.")

    chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).all()
    if not chunks:
        raise HTTPException(
            status_code=400,
            detail="لم يتم استخراج أي نص قابل للقراءة من هذا الملف بعد "
            "(قد يكون PDF ممسوحًا ضوئيًا يحتاج OCR، غير مطبَّق بعد).",
        )

    history = _recent_history(db, current_user.id, doc.id)
    _save_message(db, current_user.id, doc.id, "user", payload.question)

    top_chunks, method = retrieve_relevant_chunks(payload.question, chunks)
    context = "\n\n".join(f"[صفحة {c.page_number}]\n{c.content}" for c in top_chunks)
    user_prompt = f"محتوى المحاضرة:\n{context}\n\nسؤال الطالب: {payload.question}"

    return DOCUMENT_SYSTEM_PROMPT, user_prompt, history, top_chunks, method, doc.id


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    current_user: User = Depends(rate_limit_ai),
    db: Session = Depends(get_db),
):
    system_prompt, user_prompt, history, top_chunks, method, doc_id = _prepare_chat_context(
        payload, current_user, db
    )
    try:
        answer = chat_completion(system_prompt, user_prompt, history=history)
    except AIServiceUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except AIServiceError as e:
        raise HTTPException(status_code=502, detail=str(e))

    _save_message(db, current_user.id, doc_id, "assistant", answer)

    sources = (
        [ChatSource(page_number=c.page_number, snippet=c.content[:150]) for c in top_chunks]
        if top_chunks
        else []
    )
    return ChatResponse(answer=answer, sources=sources, retrieval_method=method)


@router.post("/chat/stream")
def chat_stream(
    payload: ChatRequest,
    current_user: User = Depends(rate_limit_ai),
    db: Session = Depends(get_db),
):
    """
    نسخة بثّية من /chat (§10): تُعيد النص تدريجيًا فور توليده بدل انتظار
    الرد الكامل — يُحسّن الإحساس بالسرعة في المحادثة بشكل كبير (يظهر
    النص كلمة بكلمة، مثل ChatGPT).

    ⚠️ قيد بنيوي مهم في أي Streaming HTTP: بمجرد إرسال أول جزء من الاستجابة
    (status 200)، **لا يمكن تغيير كود الحالة لاحقًا** حتى لو فشل الاتصال
    بـ Gemini في المنتصف. لذلك: أخطاء "لا مفتاح إطلاقًا" (503) والتحقق من
    الملف (404/400) تحدث *قبل* بدء البثّ (فتصل بكود HTTP صحيح كالمعتاد)،
    بينما أي فشل يحدث *أثناء* توليد الرد نفسه (فشل شبكة منتصف الطريق) يصل
    كحدث `{"type": "error"}` داخل تدفق البيانات نفسه، وليس كحالة HTTP.
    """
    system_prompt, user_prompt, history, top_chunks, method, doc_id = _prepare_chat_context(
        payload, current_user, db
    )

    # تحقق مبكر صريح (قبل بدء البثّ) بدل الاعتماد فقط على الاستثناء الذي
    # سيُرفَع لاحقًا من داخل الـ Generator — هذا يسمح بإرجاع 503 حقيقي.
    if not settings.gemini_api_key:
        raise HTTPException(
            status_code=503,
            detail="ميزات الذكاء الاصطناعي غير مفعّلة على الخادم. "
            "أضف GEMINI_API_KEY في ملف .env لتفعيلها.",
        )

    def event_generator():
        full_text_parts: list[str] = []
        try:
            for text_chunk in chat_completion_stream(system_prompt, user_prompt, history=history):
                full_text_parts.append(text_chunk)
                yield _sse_event({"type": "chunk", "text": text_chunk})
        except (AIServiceUnavailable, AIServiceError) as e:
            yield _sse_event({"type": "error", "detail": str(e)})
            return

        full_answer = "".join(full_text_parts)
        _save_message(db, current_user.id, doc_id, "assistant", full_answer)

        sources = (
            [{"page_number": c.page_number, "snippet": c.content[:150]} for c in top_chunks]
            if top_chunks
            else []
        )
        yield _sse_event({"type": "done", "sources": sources, "retrieval_method": method})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/chat/history", response_model=list[ChatHistoryMessage])
def get_chat_history(
    document_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """يُعيد سجل محادثة كامل (عامة إن لم يُمرَّر document_id، أو خاصة
    بملف محدَّد) — يسمح للتطبيق باستعادة المحادثة بعد إغلاقه وإعادة فتحه،
    بدل بدء محادثة فارغة في كل مرة."""
    query = db.query(ChatMessage).filter(ChatMessage.owner_id == current_user.id)
    if document_id is None:
        query = query.filter(ChatMessage.document_id.is_(None))
    else:
        query = query.filter(ChatMessage.document_id == document_id)
    return query.order_by(ChatMessage.created_at).all()
