import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rate_limit import rate_limit_ai
from app.core.security import get_current_user
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.quiz import Quiz, Question, QuizAttempt
from app.models.user import User
from app.schemas.quiz import (
    GenerateQuestionsRequest,
    QuizOut,
    QuestionPublicOut,
    QuizSummaryOut,
    QuizSubmitRequest,
    QuizAttemptResultOut,
    QuestionResult,
)
from app.services.ai_service import AIServiceUnavailable, AIServiceError
from app.services.quiz_generation import generate_questions, QuestionGenerationError

router = APIRouter(tags=["Quizzes"])


def _quiz_to_public(quiz: Quiz) -> QuizOut:
    return QuizOut(
        id=quiz.id,
        document_id=quiz.document_id,
        difficulty=quiz.difficulty,
        questions=[
            QuestionPublicOut(
                id=q.id,
                order_index=q.order_index,
                text=q.text,
                options=json.loads(q.options_json),
            )
            for q in quiz.questions
        ],
    )


@router.post(
    "/api/documents/{document_id}/questions",
    response_model=QuizOut,
    status_code=status.HTTP_201_CREATED,
)
def generate_quiz(
    document_id: int,
    payload: GenerateQuestionsRequest,
    current_user: User = Depends(rate_limit_ai),
    db: Session = Depends(get_db),
):
    """ينفّذ §11: توليد أسئلة (MCQ) من محاضرة، بعدد ومستوى صعوبة محدَّدين."""
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
        generated = generate_questions(full_text, payload.count, payload.difficulty)
    except AIServiceUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except AIServiceError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except QuestionGenerationError as e:
        # خطأ في تنسيق استجابة النموذج نفسه (نادر) — 502 لأنه فشل من طرف
        # مزوّد الذكاء الاصطناعي، وليس خطأ من المستخدم.
        raise HTTPException(status_code=502, detail=str(e))

    quiz = Quiz(document_id=doc.id, owner_id=current_user.id, difficulty=payload.difficulty)
    db.add(quiz)
    db.flush()  # للحصول على quiz.id قبل إضافة الأسئلة

    for i, q in enumerate(generated):
        db.add(Question(
            quiz_id=quiz.id,
            order_index=i,
            text=q["question"],
            options_json=json.dumps(q["options"], ensure_ascii=False),
            correct_index=q["correct_index"],
        ))
    db.commit()
    db.refresh(quiz)
    return _quiz_to_public(quiz)


@router.get("/api/quizzes", response_model=list[QuizSummaryOut])
def list_quizzes(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """سجل اختبارات المستخدم، مع أفضل نتيجة لكل اختبار إن وُجدت (§21)."""
    quizzes = (
        db.query(Quiz)
        .filter(Quiz.owner_id == current_user.id)
        .order_by(Quiz.created_at.desc())
        .all()
    )
    result = []
    for quiz in quizzes:
        best = max((a.score_percent for a in quiz.attempts), default=None)
        result.append(QuizSummaryOut(
            id=quiz.id,
            document_id=quiz.document_id,
            document_title=quiz.document.title if quiz.document else "",
            difficulty=quiz.difficulty,
            questions_count=len(quiz.questions),
            best_score_percent=best,
            created_at=quiz.created_at.isoformat(),
        ))
    return result


@router.get("/api/quizzes/{quiz_id}", response_model=QuizOut)
def get_quiz(
    quiz_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    quiz = (
        db.query(Quiz)
        .filter(Quiz.id == quiz_id, Quiz.owner_id == current_user.id)
        .first()
    )
    if not quiz:
        raise HTTPException(status_code=404, detail="الاختبار غير موجود.")
    return _quiz_to_public(quiz)


@router.post("/api/quizzes/{quiz_id}/submit", response_model=QuizAttemptResultOut)
def submit_quiz(
    quiz_id: int,
    payload: QuizSubmitRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """ينفّذ §12: تصحيح الاختبار وحفظ النتيجة فعليًا في قاعدة البيانات."""
    quiz = (
        db.query(Quiz)
        .filter(Quiz.id == quiz_id, Quiz.owner_id == current_user.id)
        .first()
    )
    if not quiz:
        raise HTTPException(status_code=404, detail="الاختبار غير موجود.")

    questions = sorted(quiz.questions, key=lambda q: q.order_index)
    if len(payload.answers) != len(questions):
        raise HTTPException(
            status_code=400,
            detail=f"عدد الإجابات ({len(payload.answers)}) لا يطابق عدد الأسئلة ({len(questions)}).",
        )

    results = []
    correct_count = 0
    for question, selected in zip(questions, payload.answers):
        is_correct = selected == question.correct_index
        if is_correct:
            correct_count += 1
        results.append(QuestionResult(
            question_id=question.id,
            text=question.text,
            options=json.loads(question.options_json),
            correct_index=question.correct_index,
            selected_index=selected,
            is_correct=is_correct,
        ))

    total = len(questions)
    score_percent = round((correct_count / total) * 100, 1) if total else 0.0

    attempt = QuizAttempt(
        quiz_id=quiz.id,
        owner_id=current_user.id,
        correct_count=correct_count,
        total_count=total,
        time_taken_seconds=payload.time_taken_seconds,
        score_percent=score_percent,
    )
    db.add(attempt)
    db.commit()

    return QuizAttemptResultOut(
        correct_count=correct_count,
        total_count=total,
        score_percent=score_percent,
        results=results,
    )
