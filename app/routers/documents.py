import os
import uuid
import json

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import rate_limit_ai
from app.core.security import get_current_user
from app.models.chat_message import ChatMessage
from app.models.document import Document
from app.models.study_session import StudySession
from app.models.document_chunk import DocumentChunk
from app.models.flashcard import Flashcard
from app.models.quiz import Quiz
from app.models.user import User
from app.schemas.document import DocumentOut
from app.schemas.ai import SummaryRequest, SummaryResponse
from app.services.pdf_service import count_pdf_pages
from app.services.text_extraction import extract_pdf_pages, extract_image_page
from app.services.chunking import chunk_pages
from app.services.ai_service import AIServiceUnavailable, AIServiceError, chat_completion, embed_text

router = APIRouter(prefix="/api/documents", tags=["Documents"])

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}

SUMMARY_LENGTH_INSTRUCTIONS = {
    "مختصر": "في 3 نقاط قصيرة كحد أقصى.",
    "متوسط": "في فقرة واحدة أو نقاط متوسطة الطول (5-7 نقاط).",
    "تفصيلي": "بتفصيل جيد يغطي كل الأفكار الرئيسية والفرعية.",
}


@router.get("", response_model=list[DocumentOut])
def list_documents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(Document)
        .filter(Document.owner_id == current_user.id)
        .order_by(Document.created_at.desc())
        .all()
    )


@router.post("/upload", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # 1) التحقق من الامتداد المسموح (§6: PDF/JPG/PNG فقط)
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="صيغة الملف غير مدعومة. المسموح: PDF, JPG, PNG.",
        )

    # 2) التحقق من الحجم (§30: تحديد حجم الملفات)
    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)
    if size_mb > settings.max_upload_size_mb:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"حجم الملف يتجاوز الحد الأقصى المسموح ({settings.max_upload_size_mb}MB).",
        )

    # 3) حفظ الملف في مجلد خاص بكل مستخدم لعزل بياناته (§30: حماية ملفات المستخدمين)
    user_dir = os.path.join(settings.upload_dir, str(current_user.id))
    os.makedirs(user_dir, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(user_dir, stored_name)
    with open(file_path, "wb") as f:
        f.write(contents)

    # 4) استخراج معلومات أولية (عدد الصفحات لملفات PDF فقط في هذه المرحلة)
    pages_count = count_pdf_pages(file_path) if ext == ".pdf" else 1

    document = Document(
        owner_id=current_user.id,
        title=file.filename or stored_name,
        folder="ملفات جديدة",
        file_path=file_path,
        file_type="pdf" if ext == ".pdf" else "image",
        pages=pages_count,
        progress=0.0,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    # 5) خط معالجة RAG (§7, §25): استخراج النص الكامل → تقسيمه إلى مقاطع →
    # (اختياري) توليد Embeddings إذا كان مفتاح Gemini مفعّلًا. لا يفشل رفع
    # الملف أبدًا بسبب هذه الخطوة — إن تعذّرت المعالجة (PDF ممسوح ضوئيًا
    # بلا نص، أو AI غير مفعَّل)، يبقى الملف محفوظًا فقط بدون مقاطع، وتُظهر
    # ميزتا الملخص والمحادثة رسالة واضحة بدل الانهيار.
    #
    # ⚠️ إصلاح خطأ حقيقي: الصور المرفوعة مباشرة (JPG/PNG، وليست PDF) كانت
    # تُتجاهَل بالكامل سابقًا — الشرط هنا كان `if ext == ".pdf"` فقط، فلا
    # يحدث أي استخراج نص للصور إطلاقًا. الآن كل امتداد له مسار معالجة صريح.
    if ext == ".pdf":
        pages_text = extract_pdf_pages(file_path)
    else:
        pages_text = extract_image_page(file_path)

    chunks = chunk_pages(pages_text)
    for c in chunks:
        embedding_json = None
        try:
            embedding_json = json.dumps(embed_text(c["content"]))
        except (AIServiceUnavailable, AIServiceError):
            pass  # سيُعاد المحاولة لاحقًا عبر بحث الكلمات المفتاحية كتراجع
        db.add(DocumentChunk(
            document_id=document.id,
            chunk_index=c["chunk_index"],
            page_number=c["page_number"],
            content=c["content"],
            embedding=embedding_json,
        ))
    db.commit()

    return document


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = (
        db.query(Document)
        .filter(Document.id == document_id, Document.owner_id == current_user.id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="الملف غير موجود.")
    return doc


@router.post("/{document_id}/summary", response_model=SummaryResponse)
def summarize_document(
    document_id: int,
    payload: SummaryRequest,
    current_user: User = Depends(rate_limit_ai),
    db: Session = Depends(get_db),
):
    """ينفّذ §8: تلخيص المحاضرة بمستويات (مختصر/متوسط/تفصيلي)."""
    doc = (
        db.query(Document)
        .filter(Document.id == document_id, Document.owner_id == current_user.id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="الملف غير موجود.")

    chunks = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == doc.id)
        .order_by(DocumentChunk.chunk_index)
        .all()
    )
    if not chunks:
        raise HTTPException(
            status_code=400,
            detail="لم يتم استخراج أي نص قابل للقراءة من هذا الملف بعد "
            "(قد يكون PDF ممسوحًا ضوئيًا يحتاج OCR، غير مطبَّق بعد).",
        )

    # نأخذ أول ~12000 حرف فقط لتفادي تجاوز حد السياق — كافٍ لمعظم المحاضرات
    # القصيرة/المتوسطة. لملفات أطول، الحل الصحيح لاحقًا هو تلخيص كل قطعة ثم
    # تلخيص الملخصات (Map-Reduce Summarization)، خارج نطاق هذه المرحلة.
    full_text = "\n\n".join(c.content for c in chunks)[:12000]
    instruction = SUMMARY_LENGTH_INSTRUCTIONS[payload.level]

    system = "أنت مساعد دراسي يلخّص محتوى المحاضرات باللغة العربية بوضوح ودقة."
    user_prompt = f"لخّص محتوى المحاضرة التالي {instruction}\n\nالمحتوى:\n{full_text}"

    try:
        summary = chat_completion(system, user_prompt)
    except AIServiceUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except AIServiceError as e:
        raise HTTPException(status_code=502, detail=str(e))

    return SummaryResponse(summary=summary, level=payload.level)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = (
        db.query(Document)
        .filter(Document.id == document_id, Document.owner_id == current_user.id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="الملف غير موجود.")

    db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).delete()
    db.query(Flashcard).filter(Flashcard.document_id == doc.id).delete()
    db.query(ChatMessage).filter(ChatMessage.document_id == doc.id).delete()
    db.query(StudySession).filter(StudySession.document_id == doc.id).delete()
    # حذف الاختبارات المرتبطة بهذا الملف — السؤال والمحاولات تُحذف تلقائيًا
    # معها عبر cascade="all, delete-orphan" المُعرَّف على علاقات Quiz.
    for quiz in db.query(Quiz).filter(Quiz.document_id == doc.id).all():
        db.delete(quiz)
    if os.path.exists(doc.file_path):
        os.remove(doc.file_path)
    db.delete(doc)
    db.commit()
    return None
