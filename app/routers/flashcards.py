from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rate_limit import rate_limit_ai
from app.core.security import get_current_user
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.flashcard import Flashcard
from app.models.user import User
from app.schemas.flashcard import GenerateFlashcardsRequest, FlashcardOut, FlashcardReviewRequest
from app.services.ai_service import AIServiceUnavailable, AIServiceError
from app.services.flashcard_generation import generate_flashcards, FlashcardGenerationError

router = APIRouter(tags=["Flashcards"])

# جدول المراجعة المتباعدة (§15): اليوم → غدًا → بعد 3 أيام → بعد 7 أيام
# → بعد 14 يومًا. الفهرس المستخدم هو (known_count - 1) بعد كل إجابة
# "أعرفها"، محدودًا بآخر عنصر في القائمة (لا يستمر بالتباعد إلى ما لا نهاية).
REVIEW_INTERVALS_DAYS = [1, 3, 7, 14]


@router.post(
    "/api/documents/{document_id}/flashcards",
    response_model=list[FlashcardOut],
    status_code=status.HTTP_201_CREATED,
)
def generate_document_flashcards(
    document_id: int,
    payload: GenerateFlashcardsRequest,
    current_user: User = Depends(rate_limit_ai),
    db: Session = Depends(get_db),
):
    """ينفّذ §14: توليد بطاقات تعليمية من محاضرة."""
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
    full_text = "\n\n".join(c.content for c in chunks)

    try:
        generated = generate_flashcards(full_text, payload.count)
    except AIServiceUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except AIServiceError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except FlashcardGenerationError as e:
        raise HTTPException(status_code=502, detail=str(e))

    cards = [
        Flashcard(document_id=doc.id, owner_id=current_user.id, front=c["front"], back=c["back"])
        for c in generated
    ]
    db.add_all(cards)
    db.commit()
    for c in cards:
        db.refresh(c)
    return cards


@router.get("/api/documents/{document_id}/flashcards", response_model=list[FlashcardOut])
def list_document_flashcards(
    document_id: int,
    due_only: bool = False,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """يُعيد البطاقات المُولَّدة مسبقًا لهذا الملف (بدون إعادة توليد).
    مع due_only=true (§15)، يُعيد فقط البطاقات المستحقة للمراجعة الآن
    (لم تُراجَع بعد، أو حان موعد مراجعتها التالي)."""
    doc = (
        db.query(Document)
        .filter(Document.id == document_id, Document.owner_id == current_user.id)
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="الملف غير موجود.")

    query = db.query(Flashcard).filter(Flashcard.document_id == doc.id)
    if due_only:
        now = datetime.now(timezone.utc)
        query = query.filter(
            (Flashcard.next_review_at.is_(None)) | (Flashcard.next_review_at <= now)
        )
    return query.order_by(Flashcard.id).all()


@router.post("/api/flashcards/{flashcard_id}/review", status_code=status.HTTP_204_NO_CONTENT)
def review_flashcard(
    flashcard_id: int,
    payload: FlashcardReviewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """يسجّل تقييم بطاقة واحدة (أعرفها/صعبة) ويحدّث موعد مراجعتها القادمة
    فعليًا حسب جدول Spaced Repetition (§15)."""
    card = (
        db.query(Flashcard)
        .filter(Flashcard.id == flashcard_id, Flashcard.owner_id == current_user.id)
        .first()
    )
    if not card:
        raise HTTPException(status_code=404, detail="البطاقة غير موجودة.")

    now = datetime.now(timezone.utc)
    if payload.known:
        card.known_count += 1
        interval_index = min(card.known_count - 1, len(REVIEW_INTERVALS_DAYS) - 1)
        card.next_review_at = now + timedelta(days=REVIEW_INTERVALS_DAYS[interval_index])
    else:
        card.difficult_count += 1
        card.known_count = 0  # إجابة خاطئة تُعيد الجدولة من البداية
        card.next_review_at = now + timedelta(days=1)
    db.commit()
    return None


@router.delete("/api/flashcards/{flashcard_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_flashcard(
    flashcard_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    card = (
        db.query(Flashcard)
        .filter(Flashcard.id == flashcard_id, Flashcard.owner_id == current_user.id)
        .first()
    )
    if not card:
        raise HTTPException(status_code=404, detail="البطاقة غير موجودة.")
    db.delete(card)
    db.commit()
    return None
