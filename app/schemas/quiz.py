from pydantic import BaseModel, Field


class GenerateQuestionsRequest(BaseModel):
    count: int = Field(default=5, ge=1, le=20)
    difficulty: str = Field(default="متوسط", pattern="^(سهل|متوسط|صعب)$")


class QuestionPublicOut(BaseModel):
    """نسخة الأسئلة أثناء خوض الاختبار — بدون الإجابة الصحيحة."""
    id: int
    order_index: int
    text: str
    options: list[str]

    class Config:
        from_attributes = True


class QuizOut(BaseModel):
    id: int
    document_id: int
    difficulty: str
    questions: list[QuestionPublicOut]

    class Config:
        from_attributes = True


class QuizSummaryOut(BaseModel):
    """نسخة مختصرة لقائمة اختبارات المستخدم (تاريخ الاختبارات)."""
    id: int
    document_id: int
    document_title: str
    difficulty: str
    questions_count: int
    best_score_percent: float | None
    created_at: str


class QuizSubmitRequest(BaseModel):
    answers: list[int]  # فهرس الاختيار المُحدَّد لكل سؤال بنفس ترتيب الأسئلة
    time_taken_seconds: int | None = None


class QuestionResult(BaseModel):
    question_id: int
    text: str
    options: list[str]
    correct_index: int
    selected_index: int | None
    is_correct: bool


class QuizAttemptResultOut(BaseModel):
    correct_count: int
    total_count: int
    score_percent: float
    results: list[QuestionResult]
