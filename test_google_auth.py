"""
اختبار منطق Google Sign-In — يُزيّف verify_google_id_token بدل استدعاء
خوادم Google فعليًا (لا نملك بيانات اعتماد OAuth حقيقية)، ويتحقق من:
تسجيل حساب جديد تلقائيًا، تسجيل الدخول لنفس الحساب لاحقًا (نفس google_id)،
وربط حساب Google بحساب بريد/كلمة مرور موجود مسبقًا بنفس البريد.
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))

DB_PATH = "test_google_auth.db"
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
os.environ["DATABASE_URL"] = f"sqlite:///./{DB_PATH}"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.core.config import settings  # noqa: E402

client = TestClient(app)
failures = []


def check(label, condition, extra=""):
    status = "OK " if condition else "FAIL"
    print(f"[{status}] {label} {extra}")
    if not condition:
        failures.append(label)


# 1) بدون GOOGLE_CLIENT_ID مُعرَّف -> 503 واضح، وليس انهيارًا أو قبولًا مزيَّفًا.
settings.google_client_id = None
r = client.post("/api/auth/google", json={"id_token": "anything"})
check("Google login without GOOGLE_CLIENT_ID returns 503", r.status_code == 503, f"-> {r.status_code} {r.text}")

# الآن نفعّل GOOGLE_CLIENT_ID (قيمة وهمية — لن تُستخدم فعليًا لأننا سنُزيّف التحقق)
settings.google_client_id = "fake-client-id.apps.googleusercontent.com"

# 2) رمز غير صالح (فشل التحقق) -> 401 واضح، وليس انهيارًا.
with patch("app.routers.auth.verify_google_id_token") as mock_verify:
    from app.services.google_auth import GoogleTokenInvalid
    mock_verify.side_effect = GoogleTokenInvalid("رمز غير صالح.")
    r = client.post("/api/auth/google", json={"id_token": "bad-token"})
    check("Invalid Google token returns 401", r.status_code == 401, f"-> {r.status_code} {r.text}")

# 3) رمز صالح (مُزيَّف) لأول مرة -> ينشئ حسابًا جديدًا تلقائيًا.
with patch("app.routers.auth.verify_google_id_token") as mock_verify:
    mock_verify.return_value = {
        "sub": "google-user-12345",
        "email": "newgoogleuser@example.com",
        "name": "Google User",
    }
    r = client.post("/api/auth/google", json={"id_token": "valid-token"})
    check("First-time Google login creates an account", r.status_code == 200, f"-> {r.status_code} {r.text}")
    if r.status_code == 200:
        body = r.json()
        check("New account has correct email/name from Google", body["user"]["email"] == "newgoogleuser@example.com" and body["user"]["name"] == "Google User", f"-> {body['user']}")
        google_token1 = body["access_token"]

# 4) نفس رمز Google (نفس sub) مرة أخرى -> يسجّل دخول لنفس الحساب، لا ينشئ حسابًا مكرَّرًا.
with patch("app.routers.auth.verify_google_id_token") as mock_verify:
    mock_verify.return_value = {
        "sub": "google-user-12345",
        "email": "newgoogleuser@example.com",
        "name": "Google User",
    }
    r = client.post("/api/auth/google", json={"id_token": "valid-token-again"})
    check("Second login with same Google account succeeds", r.status_code == 200, f"-> {r.status_code}")
    same_user_id = r.json()["user"]["id"] if r.status_code == 200 else None

r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {google_token1}"})
check(
    "Same user id across both Google logins (no duplicate account)",
    r.status_code == 200 and r.json()["id"] == same_user_id,
    f"-> {r.json() if r.status_code == 200 else r.status_code}",
)

# 5) مستخدم Google لا يستطيع تسجيل الدخول بكلمة مرور (لا يملك واحدة أصلًا) -> 401 وليس انهيارًا.
r = client.post("/api/auth/login", json={"email": "newgoogleuser@example.com", "password": "anything"})
check(
    "Google-only user cannot log in with a password (401, not a crash)",
    r.status_code == 401,
    f"-> {r.status_code} {r.text}",
)

# 6) ربط حساب Google بحساب بريد/كلمة مرور موجود مسبقًا بنفس البريد.
r = client.post(
    "/api/auth/register",
    json={"name": "Existing User", "email": "existing@example.com", "password": "secret123"},
)
check("Register a normal password-based account first", r.status_code == 201, f"-> {r.status_code}")
existing_user_id = r.json()["user"]["id"]

with patch("app.routers.auth.verify_google_id_token") as mock_verify:
    mock_verify.return_value = {
        "sub": "google-user-99999",
        "email": "existing@example.com",  # نفس بريد الحساب الموجود مسبقًا
        "name": "Existing User via Google",
    }
    r = client.post("/api/auth/google", json={"id_token": "linking-token"})
    check("Google login links to existing email-based account", r.status_code == 200, f"-> {r.status_code} {r.text}")
    check(
        "Linked account has the SAME user id as the original (not duplicated)",
        r.status_code == 200 and r.json()["user"]["id"] == existing_user_id,
        f"-> {r.json()['user'] if r.status_code == 200 else ''}",
    )

# 7) بعد الربط، يجب أن يبقى تسجيل الدخول بكلمة المرور القديمة يعمل أيضًا.
r = client.post("/api/auth/login", json={"email": "existing@example.com", "password": "secret123"})
check("Original password still works after linking Google", r.status_code == 200, f"-> {r.status_code} {r.text}")

print()
if failures:
    print(f"❌ {len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
else:
    print("✅ ALL GOOGLE AUTH CHECKS PASSED")
