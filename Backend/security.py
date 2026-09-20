from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Cookie, Depends, HTTPException, Request, status

from .config import Settings, get_settings
from .users import get_user, public_user

COOKIE_NAME = "family_session"
ALGORITHM = "HS256"
password_hasher = PasswordHasher()
dummy_password_hash = password_hasher.hash("not-an-actual-user-password")


def verify_password(password: str, encoded: str) -> bool:
    try:
        return password_hasher.verify(encoded, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_session(user, settings: Settings) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    csrf = token_urlsafe(24)
    payload = {
        "sub": str(user["id"]),
        "ver": user["auth_version"],
        "iat": now,
        "exp": now + timedelta(hours=settings.session_hours),
        "csrf": csrf,
    }
    return jwt.encode(payload, settings.app_secret, algorithm=ALGORITHM), csrf


def decode_session(token: str, settings: Settings) -> dict:
    try:
        return jwt.decode(token, settings.app_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Érvénytelen munkamenet") from exc


async def current_session(
    token: str | None = Cookie(default=None, alias=COOKIE_NAME),
    settings: Settings = Depends(get_settings),
) -> dict:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bejelentkezés szükséges")
    claims = decode_session(token, settings)
    try:
        user_id = int(claims["sub"])
        version = int(claims["ver"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Érvénytelen munkamenet") from exc
    user = get_user(settings, user_id=user_id)
    if not user or not user["is_active"] or user["auth_version"] != version:
        raise HTTPException(status_code=401, detail="A munkamenet lejárt")
    return {**claims, "user": public_user(user)}


async def admin_session(session: dict = Depends(current_session)) -> dict:
    if not session["user"]["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin jogosultság szükséges")
    return session


async def mutation_guard(
    request: Request,
    session: dict = Depends(current_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != settings.public_origin.rstrip("/"):
        raise HTTPException(status_code=403, detail="Érvénytelen origin")
    if request.headers.get("x-csrf-token") != session.get("csrf"):
        raise HTTPException(status_code=403, detail="Érvénytelen CSRF token")
    return session
