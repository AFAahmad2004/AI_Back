from datetime import datetime

from pydantic import BaseModel


class StartSessionRequest(BaseModel):
    document_id: int | None = None  # null = جلسة دراسة عامة (بلا ملف محدَّد)


class StudySessionOut(BaseModel):
    id: int
    document_id: int | None
    started_at: datetime  # يُسلسَل تلقائيًا كنص ISO 8601 في JSON

    class Config:
        from_attributes = True


class EndSessionResponse(BaseModel):
    id: int
    duration_seconds: int
