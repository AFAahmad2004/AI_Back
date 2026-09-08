from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float
from sqlalchemy.orm import relationship

from app.core.database import Base


class Document(Base):
    """
    يمثّل جدول Documents من §24. في المرحلة الحالية (MVP) نخزّن المعلومات
    الأساسية فقط؛ جداول DocumentPages/DocumentChunks (للـ RAG، راجع §25)
    تُضاف عند تنفيذ استخراج النص والـ Embeddings الفعلية.
    """

    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    title = Column(String(255), nullable=False)
    folder = Column(String(120), nullable=False, default="عام")
    file_path = Column(String(500), nullable=False)
    file_type = Column(String(20), nullable=False, default="pdf")  # pdf | image
    pages = Column(Integer, nullable=False, default=0)
    progress = Column(Float, nullable=False, default=0.0)  # 0..1، تقدّم القراءة

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    owner = relationship("User", back_populates="documents")
