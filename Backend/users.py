"""Persistent local accounts. Only the host-mounted config directory is writable."""

import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from .config import Settings

USERNAME = re.compile(r"[a-zA-Z0-9._-]{3,32}\Z")


def normalize_username(value: str) -> str:
    value = value.strip().lower()
    if not USERNAME.fullmatch(value):
        raise HTTPException(400, "A felhasználónév 3–32 karakteres lehet: betű, szám, pont, _ vagy -")
    return value


def public_user(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "username": row["username"],
        "is_admin": bool(row["is_admin"]), "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
    }


@contextmanager
def connection(settings: Settings):
    db = sqlite3.connect(settings.auth_db_path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout=10000")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db(settings: Settings) -> None:
    root = settings.shared_root.resolve(strict=False)
    db_path = settings.auth_db_path.resolve(strict=False)
    if db_path == root or root in db_path.parents:
        raise RuntimeError("AUTH_DB_PATH must be outside SHARED_ROOT")
    if not db_path.parent.is_dir() or db_path.parent.is_symlink():
        raise RuntimeError("AUTH_DB_PATH parent directory must already exist and not be a symlink")
    if db_path.is_symlink():
        raise RuntimeError("AUTH_DB_PATH may not be a symlink")
    with connection(settings) as db:
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            auth_version INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS login_attempts (
            username TEXT PRIMARY KEY,
            failures INTEGER NOT NULL,
            locked_until INTEGER NOT NULL DEFAULT 0
        )""")


def get_user(settings: Settings, *, username: str | None = None, user_id: int | None = None):
    with connection(settings) as db:
        if username is not None:
            return db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        return db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()


def all_users(settings: Settings) -> list[dict]:
    with connection(settings) as db:
        return [public_user(row) for row in db.execute("SELECT * FROM users ORDER BY username")]


def add_user(settings: Settings, username: str, password_hash: str, is_admin: bool = False, *, initial: bool = False) -> dict:
    username = normalize_username(username)
    with connection(settings) as db:
        db.execute("BEGIN IMMEDIATE")
        if initial and db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
            raise HTTPException(409, "A kezdeti admin már létezik")
        try:
            cursor = db.execute(
                "INSERT INTO users(username,password_hash,is_admin,created_at) VALUES(?,?,?,?)",
                (username, password_hash, int(is_admin), datetime.now(timezone.utc).isoformat()),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "Ez a felhasználónév már létezik") from exc
        return public_user(db.execute("SELECT * FROM users WHERE id=?", (cursor.lastrowid,)).fetchone())


def change_flags(settings: Settings, user_id: int, *, is_admin: bool | None, is_active: bool | None) -> dict:
    with connection(settings) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "Felhasználó nem található")
        admin = bool(row["is_admin"]) if is_admin is None else is_admin
        active = bool(row["is_active"]) if is_active is None else is_active
        if row["is_admin"] and row["is_active"] and not (admin and active):
            count = db.execute("SELECT COUNT(*) FROM users WHERE is_admin=1 AND is_active=1").fetchone()[0]
            if count <= 1:
                raise HTTPException(409, "Az utolsó aktív admin nem tiltható le")
        db.execute(
            "UPDATE users SET is_admin=?, is_active=?, auth_version=auth_version+1 WHERE id=?",
            (int(admin), int(active), user_id),
        )
        return public_user(db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())


def set_password(settings: Settings, user_id: int, password_hash: str) -> None:
    with connection(settings) as db:
        db.execute("BEGIN IMMEDIATE")
        updated = db.execute(
            "UPDATE users SET password_hash=?, auth_version=auth_version+1 WHERE id=?",
            (password_hash, user_id),
        )
        if not updated.rowcount:
            raise HTTPException(404, "Felhasználó nem található")
        db.execute("DELETE FROM login_attempts WHERE username=(SELECT username FROM users WHERE id=?)", (user_id,))


def get_lockout(settings: Settings, username: str) -> int:
    with connection(settings) as db:
        row = db.execute("SELECT locked_until FROM login_attempts WHERE username=?", (username,)).fetchone()
        return row["locked_until"] if row else 0


def record_login(settings: Settings, username: str, success: bool, now: int) -> None:
    with connection(settings) as db:
        db.execute("BEGIN IMMEDIATE")
        if success:
            db.execute("DELETE FROM login_attempts WHERE username=?", (username,))
        else:
            row = db.execute("SELECT failures,locked_until FROM login_attempts WHERE username=?", (username,)).fetchone()
            failures = 1 if not row or (row["locked_until"] and row["locked_until"] <= now) else row["failures"] + 1
            locked_until = now + 900 if failures >= 5 else 0
            db.execute("""INSERT INTO login_attempts(username,failures,locked_until) VALUES(?,?,?)
                ON CONFLICT(username) DO UPDATE SET failures=excluded.failures, locked_until=excluded.locked_until""",
                (username, failures, locked_until),
            )
