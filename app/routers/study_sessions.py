from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.document import Document
from app.models.study_session import StudySession
from app.models.user import User
from app.schemas.study_session import StartSessionRequest, StudySessionOut, EndSessionResponse

router = APIRouter(prefix="/api/study-sessions", tags=["StudySessions"])

# أي جلسة تتجاوز هذه المدة بلا "إنهاء" صريح (مثلًا: أغلق المستخدم التطبيق
# فجأة دون استدعاء /end) تُعتبر جلسة معطوبة ولا تُحتسَب ضمن وقت الدراسة
# عند التجميع في /api/progress، لتفادي احتساب "أيام" كوقت دراسة وهمي.
MAX_REASONABLE_SESSION_MINUTES = 180


@router.post("/start", response_model=StudySessionOut)
def start_session(
    payload: StartSessionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """يُستدعى عند دخول الطالب شاشة ملف (أو الشاشة الرئيسية لجلسة عامة)."""
    if payload.document_id is not None:
        doc = (
            db.query(Document)
            .filter(Document.id == payload.document_id, Document.owner_id == current_user.id)
            .first()
        )
        if not doc:
            raise HTTPException(status_code=404, detail="الملف غير موجود.")

    session = StudySession(owner_id=current_user.id, document_id=payload.document_id)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.post("/{session_id}/end", response_model=EndSessionResponse)
def end_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """يُستدعى عند خروج الطالب من الشاشة (أو إغلاق التطبيق بشكل طبيعي)."""
    session = (
        db.query(StudySession)
        .filter(StudySession.id == session_id, StudySession.owner_id == current_user.id)
        .first()
    )
    if not session:
        raise HTTPException(status_code=404, detail="الجلسة غير موجودة.")

    if session.ended_at is None:
        session.ended_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(session)

    return EndSessionResponse(id=session.id, duration_seconds=session.duration_seconds)
