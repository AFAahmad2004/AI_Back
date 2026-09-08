from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.core.config import settings

# `connect_args` مطلوب فقط لـ SQLite (تطوير محلي). عند التبديل إلى
# PostgreSQL في الإنتاج (§24) يُحذف هذا السطر تلقائيًا لأن الشرط لن يتحقق.
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Dependency تُستخدم في كل Endpoint يحتاج قاعدة بيانات."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
