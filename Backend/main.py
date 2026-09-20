import mimetypes
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from .config import Settings, get_settings
from .sandbox import FileSandbox, stat_without_links
from .security import COOKIE_NAME, create_session, current_session, mutation_guard, verify_password

app = FastAPI(title="Family Share", docs_url=None, redoc_url=None)
api = APIRouter(prefix="/api")


async def sandbox(settings: Settings = Depends(get_settings)) -> FileSandbox:
    return FileSandbox(settings.shared_root)


class LoginBody(BaseModel):
    username: str
    password: str


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
async def login(body: LoginBody, response: Response, settings: Settings = Depends(get_settings)):
    if body.username != settings.admin_username or not verify_password(body.password, settings.admin_password_hash):
        raise HTTPException(401, "Hibás felhasználónév vagy jelszó")
    token, csrf = create_session(body.username, settings)
    response.set_cookie(
        COOKIE_NAME, token, httponly=True, secure=settings.cookie_secure,
        samesite="strict", max_age=settings.session_hours * 3600, path="/",
    )
    return {"username": body.username, "csrf": csrf}


@api.get("/auth/me")
async def me(session: dict = Depends(current_session)):
    return {"username": session["sub"], "csrf": session["csrf"]}


@api.post("/auth/logout")
async def logout(response: Response, _: dict = Depends(mutation_guard)):
    response.delete_cookie(COOKIE_NAME, path="/")
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
