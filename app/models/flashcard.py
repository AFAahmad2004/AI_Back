from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import relationship

from app.core.database import Base


class Flashcard(Base):
    """يمثّل جدول Flashcards من §24 — بطاقة سؤال/جواب واحدة مُولَّدة من محاضرة."""

    __tablename__ = "flashcards"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    front = Column(Text, nullable=False)
    back = Column(Text, nullable=False)

    # نظام Spaced Repetition (§15): known_count/difficult_count عدّادات
    # خام، وnext_review_at هو التاريخ الفعلي الذي يُحسَب منها (راجع
    # REVIEW_INTERVALS_DAYS في routers/flashcards.py).
    known_count = Column(Integer, nullable=False, default=0)
    difficult_count = Column(Integer, nullable=False, default=0)
    next_review_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    document = relationship("Document")
