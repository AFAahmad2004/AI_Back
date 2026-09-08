from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import relationship

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    # nullable لأن مستخدمي Google Sign-In ليس لديهم كلمة مرور إطلاقًا —
    # هويتهم تُتحقَّق دائمًا عبر Google، لا عبر verify_password محليًا.
    hashed_password = Column(String(255), nullable=True)

    # مُعرَّف حساب Google الفريد (claim "sub" في ID Token) — يُملأ فقط
    # لمستخدمي "المتابعة عبر Google" (§4). NULL لمستخدمي البريد/كلمة المرور.
    google_id = Column(String(255), unique=True, index=True, nullable=True)

    # حقول اختيارية من §4 (المستوى الدراسي، التخصص...) — تُملأ لاحقًا من Profile.
    major = Column(String(120), nullable=True, default="")
    study_level = Column(String(60), nullable=True, default="")

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    documents = relationship("Document", back_populates="owner", cascade="all, delete-orphan")
