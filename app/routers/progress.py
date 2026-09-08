from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.document import Document
from app.models.quiz import QuizAttempt
from app.models.study_session import StudySession
from app.models.user import User
from app.schemas.progress import ProgressOut, TopicScoreOut, RecentQuizOut

router = APIRouter(prefix="/api/progress", tags=["Progress"])

# قواعد بسيطة وواضحة لحساب XP/Level — قابلة للتعديل لاحقًا بسهولة، الأهم أنها
# محسوبة فعليًا من نشاط حقيقي (QuizAttempts)، وليست أرقامًا ثابتة (§22).
XP_PER_CORRECT_ANSWER = 10
XP_PER_LEVEL = 500

# أي جلسة دراسة أطول من هذا الحد تُستبعَد من مجموع وقت الدراسة — على الأرجح
# جلسة لم تُغلَق بشكل صحيح (تطبيق أُغلِق فجأة بدل استدعاء /end)، فاحتسابها
# بالكامل يُضخِّم "وقت الدراسة" بشكل غير واقعي (راجع routers/study_sessions.py).
MAX_REASONABLE_SESSION_MINUTES = 180


def _compute_streak(timestamps: list[datetime]) -> int:
    """يحسب عدد الأيام المتتالية (حتى اليوم) التي فيها نشاط واحد على الأقل
    (محاولة اختبار أو جلسة دراسة). Streak حقيقي مبني على أي نشاط فعلي،
    وليس الاختبارات فقط."""
    if not timestamps:
        return 0
    unique_days = sorted({t.date() for t in timestamps}, reverse=True)
    today = datetime.now(timezone.utc).date()

    streak = 0
    expected = today
    for day in unique_days:
        if day == expected:
            streak += 1
            expected -= timedelta(days=1)
        elif day < expected:
            break
    return streak


@router.get("", response_model=ProgressOut)
def get_progress(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    ⚠️ ملاحظة صدق مهمة متبقّية: "المواضيع" هنا هي عناوين الملفات نفسها
    (وليست مواضيع فرعية داخل الملف) لأنه لا يوجد بعد نظام تصنيف بالمواضيع
    للأسئلة. "وقت الدراسة" أصبح الآن حقيقيًا فعليًا (جلسات + اختبارات)
    بدل الاعتماد على وقت الاختبارات فقط كما كان سابقًا.
    """
    files_count = db.query(Document).filter(Document.owner_id == current_user.id).count()

    attempts = (
        db.query(QuizAttempt)
        .filter(QuizAttempt.owner_id == current_user.id)
        .order_by(QuizAttempt.created_at.desc())
        .all()
    )

    quizzes_count = len(attempts)
    average_score = (
        round(sum(a.score_percent for a in attempts) / quizzes_count, 1) if quizzes_count else 0.0
    )

    # وقت الدراسة الحقيقي (§21): جلسات فعلية (فتح ملف/الرئيسية ومتابعتها)
    # + وقت الاختبارات (يبقى محتسَبًا لأنه نشاط دراسي فعلي أيضًا).
    sessions = (
        db.query(StudySession)
        .filter(StudySession.owner_id == current_user.id, StudySession.ended_at.isnot(None))
        .all()
    )
    max_seconds = MAX_REASONABLE_SESSION_MINUTES * 60
    session_seconds = sum(min(s.duration_seconds, max_seconds) for s in sessions)
    quiz_seconds = sum(a.time_taken_seconds or 0 for a in attempts)
    total_study_seconds = session_seconds + quiz_seconds

    total_correct_answers = sum(a.correct_count for a in attempts)
    total_xp = total_correct_answers * XP_PER_CORRECT_ANSWER
    level = total_xp // XP_PER_LEVEL + 1
    current_xp_in_level = total_xp % XP_PER_LEVEL

    activity_timestamps = [a.created_at for a in attempts] + [s.started_at for s in sessions]
    streak_days = _compute_streak(activity_timestamps)

    # "المواضيع": متوسط النتيجة لكل ملف (وليس تصنيفًا موضوعيًا حقيقيًا بعد).
    scores_by_document: dict[str, list[float]] = {}
    for a in attempts:
        title = a.quiz.document.title if a.quiz and a.quiz.document else "غير معروف"
        scores_by_document.setdefault(title, []).append(a.score_percent)

    topic_scores = sorted(
        (
            TopicScoreOut(label=title, percent=round(sum(scores) / len(scores), 1))
            for title, scores in scores_by_document.items()
        ),
        key=lambda t: t.percent,  # الأضعف أولًا، ليظهر في مقترحات المراجعة
    )[:6]

    recent_quizzes = [
        RecentQuizOut(
            title=a.quiz.document.title if a.quiz and a.quiz.document else "اختبار",
            score_percent=a.score_percent,
            questions_count=a.total_count,
            created_at=a.created_at.isoformat(),
        )
        for a in attempts[:10]
    ]

    return ProgressOut(
        total_study_time_seconds=total_study_seconds,
        files_count=files_count,
        quizzes_count=quizzes_count,
        average_score_percent=average_score,
        streak_days=streak_days,
        level=level,
        current_xp=current_xp_in_level,
        next_level_xp=XP_PER_LEVEL,
        topic_scores=topic_scores,
        recent_quizzes=recent_quizzes,
    )
