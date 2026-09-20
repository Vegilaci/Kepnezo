import os
from pathlib import Path, PurePosixPath

from fastapi import HTTPException


class FileSandbox:
    """Maps API-relative POSIX paths into one root and refuses every symlink."""

    RESERVED = ".family-share-tmp"

    def __init__(self, root: Path):
        if not root.exists() or not root.is_dir():
            raise RuntimeError(f"SHARED_ROOT does not exist or is not a directory: {root}")
        if root.is_symlink():
            raise RuntimeError("SHARED_ROOT itself may not be a symlink")
        self.root = root.resolve(strict=True)

    def resolve(self, relative: str = "", *, must_exist: bool = True) -> Path:
        if "\x00" in relative or "\\" in relative:
            raise HTTPException(400, "Érvénytelen elérési út")
        parsed = PurePosixPath(relative)
        if parsed.is_absolute() or any(part in ("..", ".") for part in parsed.parts):
            raise HTTPException(400, "Érvénytelen elérési út")
        if self.RESERVED in parsed.parts:
            raise HTTPException(403, "Fenntartott alkalmazáskönyvtár")

        candidate = self.root.joinpath(*parsed.parts)
        # Check every existing component with lstat before resolve. Symlinks are not
        # followed, even if they happen to point back inside the root.
        cursor = self.root
        for part in parsed.parts:
            cursor = cursor / part
            try:
                if cursor.is_symlink():
                    raise HTTPException(403, "Symlink nem használható")
            except OSError as exc:
                raise HTTPException(400, "Az útvonal nem ellenőrizhető") from exc

        try:
            resolved = candidate.resolve(strict=must_exist)
        except FileNotFoundError as exc:
            raise HTTPException(404, "A fájl vagy mappa nem található") from exc
        except OSError as exc:
            raise HTTPException(400, "Az útvonal nem ellenőrizhető") from exc
        if resolved != self.root and self.root not in resolved.parents:
            raise HTTPException(403, "Az útvonal kívül esik a megosztáson")
        return resolved

    def child(self, parent_relative: str, name: str) -> Path:
        if not name or name in (".", "..") or "/" in name or "\\" in name or "\x00" in name:
            raise HTTPException(400, "Érvénytelen név")
        parent = self.resolve(parent_relative)
        if not parent.is_dir():
            raise HTTPException(400, "A cél nem mappa")
        target = self.resolve(str(PurePosixPath(parent_relative) / name), must_exist=False)
        return target

    def relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()


def stat_without_links(path: Path):
    try:
        return path.stat(follow_symlinks=False)
    except TypeError:  # Python 3.10 Path.stat lacks follow_symlinks
        return os.stat(path, follow_symlinks=False)
