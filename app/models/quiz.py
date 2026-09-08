from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Float
from sqlalchemy.orm import relationship

from app.core.database import Base


class Quiz(Base):
    """يمثّل جدول Quizzes من §24 — مجموعة أسئلة مُولَّدة من محاضرة واحدة."""

    __tablename__ = "quizzes"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    difficulty = Column(String(20), nullable=False, default="متوسط")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    document = relationship("Document")
    questions = relationship(
        "Question", back_populates="quiz", cascade="all, delete-orphan", order_by="Question.order_index"
    )
    attempts = relationship("QuizAttempt", back_populates="quiz", cascade="all, delete-orphan")


class Question(Base):
    """يمثّل جدول Questions من §24. `options` مخزَّن كنص JSON (قائمة 4 خيارات)."""

    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, index=True)
    quiz_id = Column(Integer, ForeignKey("quizzes.id"), nullable=False)

    order_index = Column(Integer, nullable=False, default=0)
    text = Column(Text, nullable=False)
    options_json = Column(Text, nullable=False)  # json.dumps(list[str])
    correct_index = Column(Integer, nullable=False)

    quiz = relationship("Quiz", back_populates="questions")


class QuizAttempt(Base):
    """يمثّل جدول QuizAttempts من §24 — نتيجة محاولة اختبار واحدة."""

    __tablename__ = "quiz_attempts"

    id = Column(Integer, primary_key=True, index=True)
    quiz_id = Column(Integer, ForeignKey("quizzes.id"), nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    correct_count = Column(Integer, nullable=False)
    total_count = Column(Integer, nullable=False)
    time_taken_seconds = Column(Integer, nullable=True)
    score_percent = Column(Float, nullable=False)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    quiz = relationship("Quiz", back_populates="attempts")
