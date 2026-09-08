from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.user import User

# نستخدم مكتبة bcrypt مباشرة بدل passlib لتفادي مشاكل توافق الإصدارات
# المعروفة بين passlib وbcrypt الحديث، مع نفس مستوى الأمان.
BCRYPT_MAX_BYTES = 72  # حد bcrypt الأصلي لطول كلمة المرور بالبايت.

# tokenUrl يشير فقط لتوليد وثائق Swagger التفاعلية عند /docs، وليس مسارًا فعليًا مختلفًا.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def hash_password(password: str) -> str:
    truncated = password.encode("utf-8")[:BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(truncated, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    truncated = plain_password.encode("utf-8")[:BCRYPT_MAX_BYTES]
    return bcrypt.checkpw(truncated, hashed_password.encode("utf-8"))


REFRESH_TOKEN_EXPIRE_DAYS = 30


def create_access_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {"sub": subject, "exp": expire, "type": "access"}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def create_refresh_token(subject: str) -> str:
    """رمز طويل الأمد (30 يومًا) يُستخدم فقط للحصول على access_token جديد
    عبر /api/auth/refresh — لا يُقبل أبدًا كرمز دخول مباشر لأي Endpoint
    آخر (يتحقق get_current_user من type=access تحديدًا)."""
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": subject, "exp": expire, "type": "refresh"}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def _decode_token(token: str, expected_type: str) -> str:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="جلسة غير صالحة أو منتهية، الرجاء تسجيل الدخول مجددًا.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id: str | None = payload.get("sub")
        token_type = payload.get("type")
        if user_id is None or token_type != expected_type:
            raise credentials_exception
        return user_id
    except JWTError:
        raise credentials_exception


def decode_access_token(token: str) -> str:
    """يُرجع user_id (sub) من رمز دخول (access)، أو يرفع 401 إذا كان غير
    صالح/منتهيًا/من النوع الخطأ (مثلًا محاولة استخدام refresh_token هنا)."""
    return _decode_token(token, expected_type="access")


def decode_refresh_token(token: str) -> str:
    return _decode_token(token, expected_type="refresh")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    user_id = decode_access_token(token)
    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="المستخدم غير موجود.")
    return user
