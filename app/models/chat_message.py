from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.orm import relationship

from app.core.database import Base


class ChatMessage(Base):
    """يمثّل رسالة واحدة (من الطالب أو من AI) ضمن محادثة. document_id يكون
    null لمحادثة عامة (§10)، أو معرّف ملف فعلي لمحادثة RAG مرتبطة بمحاضرة.
    محادثات كل مستخدم منفصلة تمامًا (owner_id)، ومحادثات كل ملف منفصلة عن
    محادثات ملف آخر ومحادثات المستخدم العامة."""

    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True, index=True)

    role = Column(String(20), nullable=False)  # "user" أو "assistant"
    content = Column(Text, nullable=False)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    document = relationship("Document")
