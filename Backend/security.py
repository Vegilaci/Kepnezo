from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Cookie, Depends, HTTPException, Request, status

from .config import Settings, get_settings

COOKIE_NAME = "family_session"
ALGORITHM = "HS256"
password_hasher = PasswordHasher()


def verify_password(password: str, encoded: str) -> bool:
    try:
        return password_hasher.verify(encoded, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_session(username: str, settings: Settings) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    csrf = token_urlsafe(24)
    payload = {
        "sub": username,
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
    return decode_session(token, settings)


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
