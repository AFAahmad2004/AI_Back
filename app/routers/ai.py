from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rate_limit import rate_limit_ai
from app.core.security import get_current_user
from app.models.chat_message import ChatMessage
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.user import User
from app.schemas.ai import ChatRequest, ChatResponse, ChatSource, ChatHistoryMessage
from app.services.ai_service import AIServiceUnavailable, AIServiceError, chat_completion
from app.services.retrieval import retrieve_relevant_chunks

router = APIRouter(prefix="/api/ai", tags=["AI"])

# عدد رسائل السياق السابقة المُرسَلة مع كل سؤال جديد — رقم صغير يوازن بين
# "تذكّر" مفيد للمحادثة وبين تكلفة/زمن استجابة إضافيَّين لكل طلب.
MAX_HISTORY_MESSAGES = 10

DOCUMENT_SYSTEM_PROMPT = (
    "أنت مساعد دراسي ذكي. أجب على سؤال الطالب بالاعتماد فقط على المحتوى "
    "المرفق من محاضرته أدناه. إذا لم يكن الجواب موجودًا في المحتوى، صرّح "
    "بذلك بوضوح بدل تأليف إجابة من معرفتك العامة. أجب باللغة العربية "
    "بإيجاز ووضوح."
)

# محادثة عامة (§10: "اسأل AI" بلا رفع ملف) — لا RAG، لا مقاطع، إجابة من
# معرفة النموذج العامة مباشرة، بنفس شخصية "مساعد دراسي" حفاظًا على تجربة
# موحّدة سواء كانت المحادثة مرتبطة بمحاضرة أو لا.
GENERAL_SYSTEM_PROMPT = (
    "أنت مساعد دراسي ذكي يساعد الطلاب في فهم أي مادة أو مفهوم دراسي. "
    "أجب بوضوح وإيجاز باللغة العربية، وقدّم أمثلة عند الحاجة لتسهيل الفهم."
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


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    current_user: User = Depends(rate_limit_ai),
    db: Session = Depends(get_db),
):
    # لا معرّف ملف؟ محادثة عامة بلا RAG — هذا ما يسمح للطالب بسؤال الذكاء
    # الاصطناعي حتى قبل رفع أي محاضرة (§10).
    if payload.document_id is None:
        history = _recent_history(db, current_user.id, None)
        _save_message(db, current_user.id, None, "user", payload.question)
        try:
            answer = chat_completion(GENERAL_SYSTEM_PROMPT, payload.question, history=history)
        except AIServiceUnavailable as e:
            raise HTTPException(status_code=503, detail=str(e))
        except AIServiceError as e:
            raise HTTPException(status_code=502, detail=str(e))
        _save_message(db, current_user.id, None, "assistant", answer)
        return ChatResponse(answer=answer, sources=[], retrieval_method="general")

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

    try:
        answer = chat_completion(DOCUMENT_SYSTEM_PROMPT, user_prompt, history=history)
    except AIServiceUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except AIServiceError as e:
        raise HTTPException(status_code=502, detail=str(e))

    _save_message(db, current_user.id, doc.id, "assistant", answer)

    return ChatResponse(
        answer=answer,
        sources=[
            ChatSource(page_number=c.page_number, snippet=c.content[:150])
            for c in top_chunks
        ],
        retrieval_method=method,
    )


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
