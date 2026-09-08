from datetime import datetime, timezone

from sqlalchemy import Column, Integer, ForeignKey, DateTime
from sqlalchemy.orm import relationship

from app.core.database import Base


class StudySession(Base):
    """يمثّل جلسة دراسة واحدة (فتح ملف ومتابعة قراءته/مراجعته، §21) —
    الأساس لحساب "وقت الدراسة" الفعلي في Progress، بدل الاعتماد فقط على
    وقت محاولات الاختبار كما كان سابقًا.

    التطبيق يفتح جلسة (POST /api/study-sessions/start) عند دخول شاشة ملف،
    ويغلقها (POST /api/study-sessions/{id}/end) عند الخروج منها — المدة
    الفعلية المنقضية بينهما هي وقت الدراسة الحقيقي."""

    __tablename__ = "study_sessions"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)

    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    ended_at = Column(DateTime, nullable=True)

    document = relationship("Document")

    @property
    def duration_seconds(self) -> int:
        if not self.ended_at:
            return 0
        started = self.started_at
        ended = self.ended_at
        # SQLite قد يُعيد قيمًا بلا معلومات المنطقة الزمنية (naive) بعد
        # القراءة من القرص، فنطبّعها قبل الطرح لتفادي خطأ مقارنة aware/naive.
        if started.tzinfo is not None:
            started = started.replace(tzinfo=None)
        if ended.tzinfo is not None:
            ended = ended.replace(tzinfo=None)
        return max(0, int((ended - started).total_seconds()))
