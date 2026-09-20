"""Prepare the upload spool on the mounted dataset, then start FastAPI."""

import os
import stat
from pathlib import Path


root = Path(os.environ.get("SHARED_ROOT", "/data"))
temporary = root / ".family-share-tmp"
if not root.is_dir() or root.is_symlink():
    raise SystemExit("SHARED_ROOT must be an existing, non-symlink directory")
if temporary.is_symlink():
    raise SystemExit("Upload temp directory must not be a symlink")
temporary.mkdir(mode=0o700, exist_ok=True)
info = temporary.stat(follow_symlinks=False)
if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
    raise SystemExit("Upload temp directory must be owned by the app UID")
temporary.chmod(0o700)
os.environ["TMPDIR"] = str(temporary)
os.execvp(
    "uvicorn",
    ["uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000", "--workers", "2"],
)

