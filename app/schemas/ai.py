from datetime import datetime

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    # اختياري الآن: تركه فارغًا يعني محادثة عامة مع الذكاء الاصطناعي بلا
    # ربط بأي محاضرة (لا RAG، لا مقاطع، إجابة من معرفة النموذج العامة).
    document_id: int | None = None
    question: str = Field(min_length=1, max_length=2000)


class ChatSource(BaseModel):
    page_number: int | None
    snippet: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[ChatSource]
    retrieval_method: str  # "semantic" أو "keyword" — للشفافية


class ChatHistoryMessage(BaseModel):
    role: str  # "user" أو "assistant"
    content: str
    created_at: datetime  # يُسلسَل تلقائيًا كنص ISO 8601 في استجابة JSON

    class Config:
        from_attributes = True


class SummaryRequest(BaseModel):
    level: str = Field(default="متوسط", pattern="^(مختصر|متوسط|تفصيلي)$")


class SummaryResponse(BaseModel):
    summary: str
    level: str
