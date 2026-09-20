from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.sandbox import FileSandbox


def test_rejects_traversal_and_absolute(tmp_path: Path):
    box = FileSandbox(tmp_path)
    for bad in ("../etc/passwd", "/etc/passwd", "a/../../b", "a\\..\\b"):
        with pytest.raises(HTTPException):
            box.resolve(bad, must_exist=False)


def test_rejects_symlink_even_when_it_points_inside(tmp_path: Path):
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)
    box = FileSandbox(tmp_path)
    with pytest.raises(HTTPException):
        box.resolve("link")


def test_valid_child_stays_inside(tmp_path: Path):
    (tmp_path / "folder").mkdir()
    box = FileSandbox(tmp_path)
    assert box.child("folder", "file.txt") == tmp_path / "folder" / "file.txt"


def test_reserved_upload_spool_is_not_browsable(tmp_path: Path):
    (tmp_path / ".family-share-tmp").mkdir()
    box = FileSandbox(tmp_path)
    with pytest.raises(HTTPException):
        box.resolve(".family-share-tmp")
    with pytest.raises(HTTPException):
        box.resolve(".family-share-tmp/part", must_exist=False)
