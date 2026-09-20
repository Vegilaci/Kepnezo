from pathlib import Path

import httpx
import pytest
from argon2 import PasswordHasher

from backend.config import Settings, get_settings
from backend.main import app
from backend.users import add_user, init_db


@pytest.fixture
def anyio_backend():
    return "asyncio"


def make_client(tmp_path: Path) -> httpx.AsyncClient:
    settings = Settings(
        shared_root=tmp_path,
        auth_db_path=tmp_path.parent / f"{tmp_path.name}-auth.sqlite3",
        app_secret="x" * 32,
        cookie_secure=True,
        public_origin="https://files.example.com",
    )
    init_db(settings)
    add_user(settings, "family", PasswordHasher().hash("correct horse"), True, initial=True)

    async def overridden_settings():
        return settings

    app.dependency_overrides[get_settings] = overridden_settings
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://files.example.com")


async def login(client: httpx.AsyncClient) -> str:
    response = await client.post("/api/auth/login", json={"username": "family", "password": "correct horse"})
    assert response.status_code == 200
    return response.json()["csrf"]


@pytest.mark.anyio
async def test_auth_upload_listing_and_range(tmp_path: Path):
    async with make_client(tmp_path) as client:
        assert (await client.get("/api/files")).status_code == 401
        csrf = await login(client)
        headers = {"X-CSRF-Token": csrf, "Origin": "https://files.example.com"}
        response = await client.post(
            "/api/upload",
            data={"path": ""},
            files=[("files", ("movie.mp4", b"0123456789", "video/mp4"))],
            headers=headers,
        )
        assert response.status_code == 200
        listing = (await client.get("/api/files")).json()
        assert listing["items"][0]["path"] == "movie.mp4"
        assert "/mnt/" not in str(listing)
        partial = await client.get("/api/content?path=movie.mp4", headers={"Range": "bytes=2-5"})
        assert partial.status_code == 206
        assert partial.content == b"2345"
        assert partial.headers["content-range"] == "bytes 2-5/10"


@pytest.mark.anyio
async def test_csrf_origin_and_traversal_are_rejected(tmp_path: Path):
    async with make_client(tmp_path) as client:
        csrf = await login(client)
        assert (await client.delete("/api/files?path=anything")).status_code == 403
        bad_origin = await client.delete(
            "/api/files?path=anything",
            headers={"X-CSRF-Token": csrf, "Origin": "https://evil.example"},
        )
        assert bad_origin.status_code == 403
        assert (await client.get("/api/files?path=../etc")).status_code == 400


@pytest.mark.anyio
async def test_admin_can_manage_users_and_revokes_sessions(tmp_path: Path):
    async with make_client(tmp_path) as admin:
        admin_csrf = await login(admin)
        headers = {"X-CSRF-Token": admin_csrf, "Origin": "https://files.example.com"}
        created = await admin.post("/api/admin/users", json={"username":"guest", "password":"guest password 123"}, headers=headers)
        assert created.status_code == 201
        guest_id = created.json()["id"]
        assert created.json()["is_admin"] is False
        assert len((await admin.get("/api/admin/users")).json()["users"]) == 2

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://files.example.com") as guest:
            logged = await guest.post("/api/auth/login", json={"username":"guest", "password":"guest password 123"})
            assert logged.status_code == 200
            assert (await guest.get("/api/files")).status_code == 200
            assert (await guest.get("/api/admin/users")).status_code == 403
            forbidden = await guest.post(
                "/api/admin/users",
                json={"username":"intruder", "password":"a long enough password"},
                headers={"X-CSRF-Token":logged.json()["csrf"]},
            )
            assert forbidden.status_code == 403
            disabled = await admin.patch(f"/api/admin/users/{guest_id}", json={"is_active":False}, headers=headers)
            assert disabled.status_code == 200
            assert (await guest.get("/api/files")).status_code == 401
            assert (await guest.get("/api/content?path=anything")).status_code == 401


@pytest.mark.anyio
async def test_last_admin_cannot_be_disabled(tmp_path: Path):
    async with make_client(tmp_path) as client:
        csrf = await login(client)
        admin_id = (await client.get("/api/admin/users")).json()["users"][0]["id"]
        response = await client.patch(f"/api/admin/users/{admin_id}", json={"is_active":False}, headers={"X-CSRF-Token":csrf})
        assert response.status_code == 400


@pytest.mark.anyio
async def test_password_reset_invalidates_old_session(tmp_path: Path):
    async with make_client(tmp_path) as admin:
        csrf = await login(admin)
        headers = {"X-CSRF-Token": csrf, "Origin": "https://files.example.com"}
        created = await admin.post("/api/admin/users", json={"username":"member", "password":"original password 123"}, headers=headers)
        member_id = created.json()["id"]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://files.example.com") as member:
            assert (await member.post("/api/auth/login", json={"username":"member", "password":"original password 123"})).status_code == 200
            assert (await member.get("/api/files")).status_code == 200
            changed = await admin.post(f"/api/admin/users/{member_id}/password", json={"password":"replacement password 123"}, headers=headers)
            assert changed.status_code == 200
            assert (await member.get("/api/files")).status_code == 401
            assert (await member.post("/api/auth/login", json={"username":"member", "password":"original password 123"})).status_code == 401
            assert (await member.post("/api/auth/login", json={"username":"member", "password":"replacement password 123"})).status_code == 200


@pytest.mark.anyio
async def test_login_lockout(tmp_path: Path):
    async with make_client(tmp_path) as client:
        for _ in range(5):
            assert (await client.post("/api/auth/login", json={"username":"family", "password":"wrong"})).status_code == 401
        assert (await client.post("/api/auth/login", json={"username":"family", "password":"correct horse"})).status_code == 429
