from pathlib import Path

from argon2 import PasswordHasher
from fastapi.testclient import TestClient

from backend.config import Settings, get_settings
from backend.main import app


def make_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        SHARED_ROOT=tmp_path,
        APP_SECRET="x" * 32,
        ADMIN_USERNAME="family",
        ADMIN_PASSWORD_HASH=PasswordHasher().hash("correct horse"),
        COOKIE_SECURE=True,
        PUBLIC_ORIGIN="https://files.example.com",
    )
    async def overridden_settings():
        return settings

    app.dependency_overrides[get_settings] = overridden_settings
    return TestClient(app, base_url="https://files.example.com")


def login(client: TestClient) -> str:
    response = client.post("/api/auth/login", json={"username": "family", "password": "correct horse"})
    assert response.status_code == 200
    return response.json()["csrf"]


def test_auth_upload_listing_and_range(tmp_path: Path):
    with make_client(tmp_path) as client:
        assert client.get("/api/files").status_code == 401
        csrf = login(client)
        headers = {"X-CSRF-Token": csrf, "Origin": "https://files.example.com"}
        response = client.post(
            "/api/upload",
            data={"path": ""},
            files=[("files", ("movie.mp4", b"0123456789", "video/mp4"))],
            headers=headers,
        )
        assert response.status_code == 200
        listing = client.get("/api/files").json()
        assert listing["items"][0]["path"] == "movie.mp4"
        assert "/mnt/" not in str(listing)

        partial = client.get("/api/content?path=movie.mp4", headers={"Range": "bytes=2-5"})
        assert partial.status_code == 206
        assert partial.content == b"2345"
        assert partial.headers["content-range"] == "bytes 2-5/10"
        assert partial.headers["accept-ranges"] == "bytes"


def test_csrf_origin_and_traversal_are_rejected(tmp_path: Path):
    with make_client(tmp_path) as client:
        csrf = login(client)
        assert client.delete("/api/files?path=anything").status_code == 403
        bad_origin = client.delete(
            "/api/files?path=anything",
            headers={"X-CSRF-Token": csrf, "Origin": "https://evil.example"},
        )
        assert bad_origin.status_code == 403
        assert client.get("/api/files?path=../etc").status_code == 400
