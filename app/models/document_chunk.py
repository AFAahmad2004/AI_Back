from sqlalchemy import Column, Integer, String, Text, ForeignKey
from sqlalchemy.orm import relationship

from app.core.database import Base


class DocumentChunk(Base):
    """
    يمثّل جدول DocumentChunks من §24 — كل صف هو مقطع نصي من محاضرة، مع
    embedding اختياري (يُملأ فقط إذا كان OPENAI_API_KEY مُعرَّفًا). في
    الإنتاج يُستبدل عمود `embedding` (المخزَّن هنا كنص JSON لتوافق SQLite)
    بعمود Vector فعلي عبر امتداد pgvector على PostgreSQL (راجع §25).
    """

    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)

    chunk_index = Column(Integer, nullable=False)
    page_number = Column(Integer, nullable=True)
    content = Column(Text, nullable=False)

    # JSON-encoded list[float] أو None إذا لم يُفعَّل الذكاء الاصطناعي بعد.
    embedding = Column(Text, nullable=True)

    document = relationship("Document")
