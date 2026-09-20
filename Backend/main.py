import mimetypes
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .config import Settings, get_settings
from .sandbox import FileSandbox, stat_without_links
from .security import COOKIE_NAME, admin_session, create_session, current_session, dummy_password_hash, mutation_guard, password_hasher, verify_password
from .users import add_user, all_users, change_flags, get_lockout, get_user, init_db, normalize_username, record_login, set_password

@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db(get_settings())
    yield


app = FastAPI(title="Family Share", docs_url=None, redoc_url=None, lifespan=lifespan)
api = APIRouter(prefix="/api")


async def sandbox(settings: Settings = Depends(get_settings)) -> FileSandbox:
    return FileSandbox(settings.shared_root)


class LoginBody(BaseModel):
    username: str = Field(max_length=32)
    password: str = Field(max_length=1024)


class NewUserBody(BaseModel):
    username: str
    password: str = Field(min_length=12, max_length=1024)
    is_admin: bool = False


class UserFlagsBody(BaseModel):
    is_admin: bool | None = None
    is_active: bool | None = None


class PasswordBody(BaseModel):
    password: str = Field(min_length=12, max_length=1024)


class OwnPasswordBody(PasswordBody):
    current_password: str = Field(max_length=1024)


class PathBody(BaseModel):
    path: str = ""


class RenameBody(BaseModel):
    path: str
    new_name: str


def item_json(path: Path, box: FileSandbox) -> dict:
    st = stat_without_links(path)
    is_link = path.is_symlink()
    return {
        "name": path.name,
        "path": box.relative(path),
        "type": "blocked" if is_link else ("directory" if path.is_dir() else "file"),
        "size": None if path.is_dir() or is_link else st.st_size,
        "modified": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
        "mime": None if path.is_dir() or is_link else (mimetypes.guess_type(path.name)[0] or "application/octet-stream"),
    }


@api.post("/auth/login")
async def login(body: LoginBody, request: Request, response: Response, settings: Settings = Depends(get_settings)):
    from time import time
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != settings.public_origin.rstrip("/"):
        raise HTTPException(403, "Érvénytelen origin")
    username = body.username.strip().lower()
    user = get_user(settings, username=username)
    now = int(time())
    if user and get_lockout(settings, username) > now:
        raise HTTPException(429, "Túl sok hibás próbálkozás; próbáld később")
    valid_password = verify_password(body.password, user["password_hash"] if user else dummy_password_hash)
    if not user or not user["is_active"] or not valid_password:
        if user:
            record_login(settings, username, False, now)
        raise HTTPException(401, "Hibás felhasználónév vagy jelszó")
    record_login(settings, username, True, now)
    token, csrf = create_session(user, settings)
    response.set_cookie(
        COOKIE_NAME, token, httponly=True, secure=settings.cookie_secure,
        samesite="strict", max_age=settings.session_hours * 3600, path="/",
    )
    return {"username": user["username"], "is_admin": bool(user["is_admin"]), "csrf": csrf}


@api.get("/auth/me")
async def me(session: dict = Depends(current_session)):
    return {"username": session["user"]["username"], "is_admin": session["user"]["is_admin"], "csrf": session["csrf"]}


@api.post("/auth/logout")
async def logout(response: Response, _: dict = Depends(mutation_guard)):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@api.post("/auth/password")
async def own_password(body: OwnPasswordBody, response: Response, session: dict = Depends(mutation_guard), settings: Settings = Depends(get_settings)):
    user = get_user(settings, user_id=session["user"]["id"])
    if not verify_password(body.current_password, user["password_hash"]):
        raise HTTPException(400, "A jelenlegi jelszó hibás")
    set_password(settings, user["id"], password_hasher.hash(body.password))
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@api.get("/admin/users")
async def list_users(_: dict = Depends(admin_session), settings: Settings = Depends(get_settings)):
    return {"users": all_users(settings)}


@api.post("/admin/users", status_code=201)
async def create_user(body: NewUserBody, session: dict = Depends(mutation_guard), settings: Settings = Depends(get_settings)):
    if not session["user"]["is_admin"]:
        raise HTTPException(403, "Admin jogosultság szükséges")
    return add_user(settings, normalize_username(body.username), password_hasher.hash(body.password), body.is_admin)


@api.patch("/admin/users/{user_id}")
async def update_user(user_id: int, body: UserFlagsBody, session: dict = Depends(mutation_guard), settings: Settings = Depends(get_settings)):
    if not session["user"]["is_admin"]:
        raise HTTPException(403, "Admin jogosultság szükséges")
    if body.is_admin is None and body.is_active is None:
        raise HTTPException(400, "Nincs módosítás")
    if user_id == session["user"]["id"] and (body.is_admin is False or body.is_active is False):
        raise HTTPException(400, "Saját admin fiók nem tiltható le")
    return change_flags(settings, user_id, is_admin=body.is_admin, is_active=body.is_active)


@api.post("/admin/users/{user_id}/password")
async def reset_password(user_id: int, body: PasswordBody, session: dict = Depends(mutation_guard), settings: Settings = Depends(get_settings)):
    if not session["user"]["is_admin"]:
        raise HTTPException(403, "Admin jogosultság szükséges")
    set_password(settings, user_id, password_hasher.hash(body.password))
    return {"ok": True}


@api.get("/files")
async def list_files(path: str = "", _: dict = Depends(current_session), box: FileSandbox = Depends(sandbox)):
    folder = box.resolve(path)
    if not folder.is_dir():
        raise HTTPException(400, "A megadott útvonal nem mappa")
    try:
        items = [item_json(child, box) for child in folder.iterdir() if not (folder == box.root and child.name == box.RESERVED)]
    except PermissionError as exc:
        raise HTTPException(403, "Nincs jogosultság a mappához") from exc
    items.sort(key=lambda x: (x["type"] != "directory", x["name"].casefold()))
    return {"path": box.relative(folder), "items": items}


def parse_range(value: str, size: int) -> tuple[int, int]:
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value.strip())
    if not match or "," in value:
        raise HTTPException(416, headers={"Content-Range": f"bytes */{size}"})
    first, last = match.groups()
    if not first:
        length = int(last or 0)
        if length <= 0:
            raise HTTPException(416, headers={"Content-Range": f"bytes */{size}"})
        start, end = max(0, size - length), size - 1
    else:
        start = int(first)
        end = min(int(last), size - 1) if last else size - 1
    if start >= size or start > end:
        raise HTTPException(416, headers={"Content-Range": f"bytes */{size}"})
    return start, end


async def file_chunks(path: Path, start: int, length: int, chunk_size: int = 1024 * 1024):
    with path.open("rb") as handle:
        handle.seek(start)
        remaining = length
        while remaining:
            chunk = handle.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@api.get("/content")
async def content(request: Request, path: str, download: bool = False, _: dict = Depends(current_session), box: FileSandbox = Depends(sandbox)):
    file_path = box.resolve(path)
    if not file_path.is_file():
        raise HTTPException(400, "A megadott útvonal nem fájl")
    size = stat_without_links(file_path).st_size
    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    disposition = "attachment" if download else "inline"
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(file_path.name)}",
        "X-Content-Type-Options": "nosniff",
    }
    range_header = request.headers.get("range")
    if range_header:
        start, end = parse_range(range_header, size)
        headers.update({"Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(end - start + 1)})
        return StreamingResponse(file_chunks(file_path, start, end - start + 1), status_code=206, media_type=mime, headers=headers)
    headers["Content-Length"] = str(size)
    return StreamingResponse(file_chunks(file_path, 0, size), media_type=mime, headers=headers)


@api.post("/folders")
async def create_folder(body: PathBody, name: str, _: dict = Depends(mutation_guard), box: FileSandbox = Depends(sandbox)):
    target = box.child(body.path, name)
    try:
        target.mkdir()
    except FileExistsError as exc:
        raise HTTPException(409, "Már létezik ilyen nevű elem") from exc
    return item_json(box.resolve(box.relative(target)), box)


@api.post("/rename")
async def rename(body: RenameBody, _: dict = Depends(mutation_guard), box: FileSandbox = Depends(sandbox)):
    source = box.resolve(body.path)
    if source == box.root:
        raise HTTPException(400, "A gyökérmappa nem nevezhető át")
    target = box.child(box.relative(source.parent), body.new_name)
    if target.exists():
        raise HTTPException(409, "Már létezik ilyen nevű elem")
    source.rename(target)
    return item_json(box.resolve(box.relative(target)), box)


@api.delete("/files")
async def delete(path: str, _: dict = Depends(mutation_guard), box: FileSandbox = Depends(sandbox)):
    target = box.resolve(path)
    if target == box.root:
        raise HTTPException(400, "A gyökérmappa nem törölhető")
    if target.is_dir():
        try:
            target.rmdir()  # Deliberately only empty folders.
        except OSError as exc:
            raise HTTPException(409, "A mappa nem üres") from exc
    else:
        target.unlink()
    return {"ok": True}


@api.post("/upload")
async def upload(
    path: Annotated[str, Form()] = "",
    files: list[UploadFile] = File(...),
    _: dict = Depends(mutation_guard),
    box: FileSandbox = Depends(sandbox),
):
    uploaded = []
    for incoming in files:
        target = box.child(path, incoming.filename or "")
        if target.exists():
            raise HTTPException(409, f"Már létezik: {target.name}")
        temp = target.with_name(f".{target.name}.{os.getpid()}.upload")
        # Revalidate the temporary destination immediately before opening it.
        box.resolve(box.relative(temp), must_exist=False)
        try:
            with temp.open("xb") as output:
                while chunk := await incoming.read(1024 * 1024):
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            box.resolve(box.relative(temp)).replace(target)
            uploaded.append(item_json(box.resolve(box.relative(target)), box))
        except FileExistsError as exc:
            raise HTTPException(409, "Ideiglenes feltöltési ütközés") from exc
        finally:
            await incoming.close()
            if temp.exists() and not temp.is_symlink():
                temp.unlink(missing_ok=True)
    return {"items": uploaded}


app.include_router(api)


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
