from pydantic import BaseModel


class TopicScoreOut(BaseModel):
    label: str
    percent: float  # 0..100


class RecentQuizOut(BaseModel):
    title: str
    score_percent: float
    questions_count: int
    created_at: str


class ProgressOut(BaseModel):
    total_study_time_seconds: int
    files_count: int
    quizzes_count: int
    average_score_percent: float
    streak_days: int
    level: int
    current_xp: int
    next_level_xp: int
    topic_scores: list[TopicScoreOut]
    recent_quizzes: list[RecentQuizOut]
