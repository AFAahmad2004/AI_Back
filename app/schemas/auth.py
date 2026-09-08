from pydantic import BaseModel, EmailStr, Field


class UserRegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    name: str
    email: EmailStr
    major: str | None = ""
    study_level: str | None = ""

    class Config:
        from_attributes = True


class RefreshRequest(BaseModel):
    refresh_token: str


class GoogleAuthRequest(BaseModel):
    # ID Token الخام من Google Sign-In في Flutter (وليس Access Token) —
    # هذا ما يحمل هوية المستخدم المُوقَّعة رقميًا من Google والتي يتحقق
    # منها الخادم فعليًا (§4).
    id_token: str


class UpdateProfileRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    major: str | None = Field(default=None, max_length=120)
    study_level: str | None = Field(default=None, max_length=60)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut
