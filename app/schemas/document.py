from datetime import datetime

from pydantic import BaseModel


class DocumentOut(BaseModel):
    id: int
    title: str
    folder: str
    file_type: str
    pages: int
    progress: float
    created_at: datetime

    class Config:
        from_attributes = True
