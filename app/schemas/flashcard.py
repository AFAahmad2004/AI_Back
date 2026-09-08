from pydantic import BaseModel, Field


class GenerateFlashcardsRequest(BaseModel):
    count: int = Field(default=8, ge=1, le=30)


class FlashcardOut(BaseModel):
    id: int
    front: str
    back: str

    class Config:
        from_attributes = True


class FlashcardReviewRequest(BaseModel):
    known: bool
