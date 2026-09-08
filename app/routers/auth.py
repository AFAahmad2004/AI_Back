from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.auth import (
    GoogleAuthRequest,
    RefreshRequest,
    TokenResponse,
    UpdateProfileRequest,
    UserLoginRequest,
    UserOut,
    UserRegisterRequest,
)
from app.services.google_auth import GoogleAuthUnavailable, GoogleTokenInvalid, verify_google_id_token

router = APIRouter(prefix="/api/auth", tags=["Auth"])


def _issue_tokens(user: User) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(subject=str(user.id)),
        refresh_token=create_refresh_token(subject=str(user.id)),
        user=UserOut.model_validate(user),
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(payload: UserRegisterRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="هذا البريد الإلكتروني مسجّل مسبقًا.")

    user = User(
        name=payload.name,
        email=payload.email,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return _issue_tokens(user)


@router.post("/login", response_model=TokenResponse)
def login(payload: UserLoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    # `user.hashed_password` قد تكون None لمستخدم أنشأ حسابه عبر Google
    # فقط — لا نمرّرها أبدًا لـ verify_password في هذه الحالة (كانت ستُسبّب
    # خطأ داخلي بدل رسالة واضحة).
    if not user or not user.hashed_password or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="البريد الإلكتروني أو كلمة المرور غير صحيحة.")

    return _issue_tokens(user)


@router.post("/google", response_model=TokenResponse)
def google_login(payload: GoogleAuthRequest, db: Session = Depends(get_db)):
    """يسجّل الدخول أو ينشئ حسابًا جديدًا تلقائيًا عبر "المتابعة عبر Google"
    (§4). يتحقق من صحة ID Token فعليًا مع خوادم Google قبل أي شيء آخر."""
    try:
        google_payload = verify_google_id_token(payload.id_token)
    except GoogleAuthUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except GoogleTokenInvalid as e:
        raise HTTPException(status_code=401, detail=str(e))

    google_id = google_payload["sub"]
    email = google_payload["email"]
    name = google_payload.get("name") or email.split("@")[0]

    user = db.query(User).filter(User.google_id == google_id).first()
    if not user:
        # لم يُسجَّل بهذا الحساب من قبل — لكن ربما لديه حساب بنفس البريد
        # أُنشئ سابقًا بكلمة مرور عادية؛ نربطهما معًا بدل إنشاء تكرار.
        user = db.query(User).filter(User.email == email).first()
        if user:
            user.google_id = google_id
        else:
            user = User(name=name, email=email, google_id=google_id, hashed_password=None)
            db.add(user)
        db.commit()
        db.refresh(user)

    return _issue_tokens(user)


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    """يُصدر access_token جديدًا (ورمز تحديث جديدًا أيضًا — تدوير كامل)
    باستخدام refresh_token صالح، دون الحاجة لإعادة تسجيل الدخول بكلمة
    المرور. لا يتطلّب Authorization Header لأن access_token قد يكون
    منتهي الصلاحية أصلًا — هذا هو بيت القصيد من هذا الـ Endpoint."""
    user_id = decode_refresh_token(payload.refresh_token)
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise HTTPException(status_code=401, detail="المستخدم غير موجود.")

    return _issue_tokens(user)


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return UserOut.model_validate(current_user)


@router.patch("/me", response_model=UserOut)
def update_me(
    payload: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """يحدّث الحقول الاختيارية للملف الشخصي (الاسم، التخصص، المستوى
    الدراسي). أي حقل يصل بقيمة None لا يُعدَّل — فقط الحقول المُرسَلة فعليًا."""
    if payload.name is not None:
        current_user.name = payload.name
    if payload.major is not None:
        current_user.major = payload.major
    if payload.study_level is not None:
        current_user.study_level = payload.study_level
    db.commit()
    db.refresh(current_user)
    return UserOut.model_validate(current_user)
