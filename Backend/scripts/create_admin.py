"""One-time, interactive bootstrap. Run: python -m backend.scripts.create_admin"""

from getpass import getpass

from fastapi import HTTPException

from backend.config import get_settings
from backend.security import password_hasher
from backend.users import add_user, init_db, normalize_username


settings = get_settings()
init_db(settings)
username = normalize_username(input("Kezdeti admin felhasználónév: "))
password = getpass("Jelszó (legalább 12 karakter): ")
confirm = getpass("Jelszó újra: ")
if len(password) < 12 or password != confirm:
    raise SystemExit("A jelszó rövid vagy a két jelszó nem egyezik.")
try:
    add_user(settings, username, password_hasher.hash(password), True, initial=True)
except HTTPException as exc:
    raise SystemExit(exc.detail) from exc
print(f"Admin létrehozva: {username}")

